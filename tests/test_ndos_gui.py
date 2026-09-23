"""Tests for the local interface server.

This serves a program that can read any path it is pointed at, so most of what
matters here is what it refuses. It listens on the loopback address only, and
a page from anywhere else must not be able to talk to it.
"""

import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ndos_gui
from ndos_gui import (
    ApiError,
    api_browse,
    api_check,
    api_link,
    api_open,
    api_query,
    job_state,
    start_job,
)

TOKEN = "token-for-tests"


class ServerTestCase(unittest.TestCase):
    """A real server on a real socket, since the guards are HTTP behaviour."""

    @classmethod
    def setUpClass(cls):
        cls.httpd, url = ndos_gui.serve(port=0, open_browser=False, token=TOKEN)
        cls.base = url.split("/?")[0]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def call(self, path, payload=None, token=TOKEN, origin=None, host=None):
        request = urllib.request.Request(self.base + path)
        if token is not None:
            request.add_header("X-NDOS-Token", token)
        if origin:
            request.add_header("Origin", origin)
        if host:
            request.add_header("Host", host)
        if payload is not None:
            request.data = json.dumps(payload).encode("utf-8")
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            body = error.read()
            try:
                return error.code, json.loads(body or b"{}")
            except json.JSONDecodeError:
                return error.code, {"raw": body[:200].decode("utf-8", "replace")}


class AccessTests(ServerTestCase):
    def test_a_valid_token_is_answered(self):
        status, body = self.call("/api/status")
        self.assertEqual(status, 200)
        self.assertIn("spec_version", body)

    def test_no_token_is_refused(self):
        self.assertEqual(self.call("/api/status", token=None)[0], 403)

    def test_a_wrong_token_is_refused(self):
        self.assertEqual(self.call("/api/status", token="guess")[0], 403)

    def test_a_page_from_another_origin_is_refused(self):
        # The reason the token exists: a site open in the same browser can
        # send requests to localhost, and must not be able to read the disk.
        status, _ = self.call("/api/status", origin="https://example.com")
        self.assertEqual(status, 403)

    def test_a_request_claiming_another_host_is_refused(self):
        self.assertEqual(self.call("/api/status", host="example.com")[0], 403)

    def test_our_own_origin_is_allowed(self):
        status, _ = self.call("/api/status", origin=self.base)
        self.assertEqual(status, 200)

    def test_an_unknown_endpoint_is_not_found(self):
        self.assertEqual(self.call("/api/nothing")[0], 404)

    def test_a_post_outside_the_api_is_not_found(self):
        self.assertEqual(self.call("/elsewhere", payload={})[0], 404)

    def test_a_body_that_is_not_json_is_rejected(self):
        request = urllib.request.Request(self.base + "/api/browse", data=b"not json")
        request.add_header("X-NDOS-Token", TOKEN)
        request.add_header("Content-Type", "application/json")
        try:
            urllib.request.urlopen(request, timeout=10)
            self.fail("expected a rejection")
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 400)


class BrowseTests(ServerTestCase):
    def test_browsing_lists_directories_for_the_folder_picker(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "raw_data").mkdir()
            (base / "notes.txt").write_text("x", encoding="utf-8")

            status, body = self.call("/api/browse", {"path": str(base)})

            self.assertEqual(status, 200)
            self.assertEqual([d["name"] for d in body["directories"]], ["raw_data"])
            self.assertEqual(body["file_count"], 1)
            self.assertIsNotNone(body["parent"])

    def test_a_project_is_recognised_while_browsing(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for name in ("raw_data", "processed_data", "metadata"):
                (base / name).mkdir()
            _, body = self.call("/api/browse", {"path": str(base)})
            self.assertTrue(body["is_project"])

    def test_browsing_something_that_is_not_a_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "a.txt"
            path.write_text("x", encoding="utf-8")
            self.assertEqual(self.call("/api/browse", {"path": str(path)})[0], 404)

    def test_hidden_entries_are_left_out(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / ".hidden").mkdir()
            (base / "visible").mkdir()
            _, body = self.call("/api/browse", {"path": str(base)})
            self.assertEqual([d["name"] for d in body["directories"]], ["visible"])


class StaticTests(ServerTestCase):
    def test_a_path_escaping_the_interface_directory_is_refused(self):
        status, _ = self.call("/../../../etc/passwd", token=None)
        # Either refused outright or resolved back inside; never the file.
        self.assertIn(status, (403, 404, 503))

    def test_a_missing_interface_explains_how_to_build_it(self):
        if ndos_gui.STATIC_ROOT.is_dir():
            self.skipTest("the interface is built in this checkout")
        status, body = self.call("/", token=None)
        self.assertEqual(status, 503)
        # The helper keeps only the first 200 bytes, so match the title.
        self.assertIn("interface not built", body.get("raw", ""))


class WorkTests(unittest.TestCase):
    """Slow work runs in the background so the page never looks dead."""

    def _wait(self, job_id, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            state = job_state(job_id)
            if state["state"] != "running":
                return state
            time.sleep(0.02)
        self.fail("job did not finish")

    def test_a_job_reports_its_result(self):
        job = start_job("test", lambda report: {"answer": 42})
        self.assertEqual(self._wait(job)["result"], {"answer": 42})

    def test_a_job_can_report_progress_while_it_runs(self):
        seen = threading.Event()

        def work(report):
            report({"files": 10})
            seen.wait(1)
            return {"done": True}

        job = start_job("test", work)
        for _ in range(100):
            if job_state(job)["progress"]:
                break
            time.sleep(0.01)
        self.assertEqual(job_state(job)["progress"], {"files": 10})
        seen.set()
        self._wait(job)

    def test_a_failing_job_is_recorded_rather_than_taking_the_server_down(self):
        def work(report):
            raise RuntimeError("something broke")

        state = self._wait(start_job("test", work))
        self.assertEqual(state["state"], "failed")
        self.assertIn("something broke", state["error"])

    def test_asking_for_a_job_that_does_not_exist(self):
        with self.assertRaises(ApiError):
            job_state("nope")


class ApiUnitTests(unittest.TestCase):
    def test_browse_refuses_an_unreadable_directory(self):
        with self.assertRaises(ApiError):
            api_browse({"path": "/definitely/not/here"})

    def test_status_reports_the_specification_version(self):
        import ndos_validate

        self.assertEqual(
            ndos_gui.api_status({})["spec_version"], ndos_validate.SPEC_VERSION
        )


class GeneratedFieldTests(unittest.TestCase):
    """The interface must not disagree with the tools about the standard.

    A hand-written copy of these definitions drifted once: the interface
    offered "male" and "female" where the standard says F and M, and could not
    express a lesion at all. Both would have passed unnoticed.
    """

    ROOT = Path(__file__).resolve().parent.parent
    GENERATED = ROOT / "gui" / "src" / "lib" / "ndos-generated.ts"

    def test_the_generated_file_is_current(self):
        import subprocess

        result = subprocess.run(
            [sys.executable, str(self.ROOT / "scripts" / "generate_gui_fields.py"), "--check"],
            capture_output=True, text=True,
        )
        self.assertEqual(
            result.returncode, 0,
            f"{result.stdout}{result.stderr}",
        )

    def test_every_vocabulary_reaches_the_interface(self):
        import ndos_table

        text = self.GENERATED.read_text(encoding="utf-8")
        for field, allowed in ndos_table.VOCABULARIES.items():
            for value in allowed:
                self.assertIn(
                    f'"{value}"', text,
                    f"{field} value {value!r} never reaches the interface",
                )

    def test_the_values_that_drifted_are_now_right(self):
        text = self.GENERATED.read_text(encoding="utf-8")
        # What the hand-written copy got wrong.
        self.assertIn('"lesion"', text)
        self.assertIn('"stimulation"', text)
        self.assertNotIn('"female"', text.split("synonyms")[0])

    def test_synonyms_travel_with_the_vocabularies(self):
        # So that what someone types in the interface is what the tools accept.
        text = self.GENERATED.read_text(encoding="utf-8")
        self.assertIn('"mouse"', text)
        self.assertIn('"ephys"', text)


class ShippedInterfaceTests(unittest.TestCase):
    """The built interface in the package must be the one in gui/.

    It ships built so that installing the package is the whole install. The
    price is that it can go stale invisibly: the bundle is unreadable and its
    filenames are hashes, so an interface a version behind looks exactly like
    a current one.
    """

    ROOT = Path(__file__).resolve().parent.parent

    def test_the_shipped_build_matches_its_sources(self):
        import subprocess

        result = subprocess.run(
            [sys.executable, str(self.ROOT / "scripts" / "vendor_gui.py"), "--check"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, f"{result.stdout}{result.stderr}")

    def test_the_page_the_server_would_serve_exists(self):
        import ndos_gui

        index = ndos_gui.STATIC_ROOT / "index.html"
        self.assertTrue(index.is_file(), f"no interface at {ndos_gui.STATIC_ROOT}")
        # Nothing may be fetched from the network: a lab machine need not have one.
        markup = index.read_text(encoding="utf-8")
        self.assertNotIn("http://", markup)
        self.assertNotIn("https://", markup)


class QueryTests(unittest.TestCase):
    """The answer a cohort query is allowed to give.

    A session that never recorded a species is not a session known not to be
    a mouse. The page used to compare strings itself and had only two
    outcomes, so it reported the second when the truth was the first -- the
    single mistake this project exists to prevent.
    """

    #: Two sessions belonging to two animals. Species lives on the animal,
    #: which is the join the page cannot do for itself.
    SESSIONS = (
        "ndos_id,observed_path,observed_file_count,observed_bytes,subject_id,session_date\n"
        "ndos-aaaa,raw_data/M01/20250314,2,2856,M01,2025-03-14\n"
        "ndos-bbbb,raw_data/M02/20250321,2,2856,M02,2025-03-21\n"
    )
    ANIMALS = "subject_id,species,strain,sex\nM01,{value}\nM02,{value}\n"
    PROCEDURES = "procedure_id,subject_id,procedure_date,procedure_type\n"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        self.metadata = self.root / "metadata"
        self.metadata.mkdir()
        import ndos_table

        (self.metadata / ndos_table.SESSIONS_FILE).write_text(
            self.SESSIONS, encoding="utf-8"
        )
        self._record_species("")
        (self.metadata / ndos_table.PROCEDURES_FILE).write_text(
            self.PROCEDURES, encoding="utf-8"
        )

    def _record_species(self, value):
        """Fill in the species column, the way a person filling a sheet would."""
        import ndos_table

        row = f"{value},," if value else ",,"
        (self.metadata / ndos_table.ANIMALS_FILE).write_text(
            self.ANIMALS.format(value=row), encoding="utf-8"
        )

    def test_a_field_nobody_filled_in_cannot_rule_a_session_out(self):
        result = api_query({"path": str(self.root), "constraints": ["species=mouse"]})

        self.assertEqual(result["counts"]["excluded"], 0, "absence was read as contradiction")
        self.assertEqual(result["counts"]["matched"], 0)
        self.assertEqual(
            result["counts"]["unresolved"], result["counts"]["considered"]
        )
        self.assertTrue(result["diagnosis"], "no explanation of why nothing matched")
        self.assertIn("ruled out", " ".join(result["diagnosis"]))

    def test_a_recorded_value_that_disagrees_does_rule_a_session_out(self):
        self._record_species("rat")
        result = api_query({"path": str(self.root), "constraints": ["species=mouse"]})

        self.assertEqual(result["counts"]["matched"], 0)
        self.assertEqual(result["counts"]["unresolved"], 0)
        self.assertEqual(
            result["counts"]["excluded"], result["counts"]["considered"],
            "a recorded contradiction should exclude",
        )

    def test_a_recorded_value_that_agrees_matches_and_cites_why(self):
        self._record_species("mouse")
        result = api_query({"path": str(self.root), "constraints": ["species=mouse"]})

        self.assertEqual(
            result["counts"]["matched"], result["counts"]["considered"]
        )
        first = result["matched"][0]
        self.assertTrue(first["evidence"], "matched without citing anything")
        self.assertEqual(first["evidence"][0]["constraint"], "species=mouse")

    def test_the_three_groups_account_for_every_session(self):
        self._record_species("mouse")
        result = api_query({"path": str(self.root), "constraints": ["species=mouse"]})
        counts = result["counts"]
        self.assertEqual(
            counts["matched"] + counts["unresolved"] + counts["excluded"],
            counts["considered"],
            "sessions went missing between the groups",
        )

    def test_a_query_nobody_can_parse_is_refused_in_words(self):
        with self.assertRaises(ApiError) as caught:
            api_query({"path": str(self.root), "constraints": ["species"]})
        self.assertNotIn("Traceback", str(caught.exception))

    def test_linking_writes_nothing(self):
        before = sorted(p.name for p in (self.root / "metadata").iterdir())
        api_link({"path": str(self.root)})
        after = sorted(p.name for p in (self.root / "metadata").iterdir())
        self.assertEqual(before, after)

    def test_a_project_without_tables_says_what_to_run(self):
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaises(ApiError) as caught:
                api_link({"path": empty})
        self.assertIn("table export", str(caught.exception))

    def test_the_tables_can_be_checked_where_they_are(self):
        result = api_check({"path": str(self.root)})
        self.assertEqual(result["row_count"], 2)
        self.assertIn("completeness", result)
        self.assertTrue(result["directory"].endswith("metadata"))


class OpenTests(unittest.TestCase):
    """Reading a file by name, rather than making someone drag it in."""

    def test_a_json_document_can_be_opened_by_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps({"manifest_version": "0.2"}), encoding="utf-8")
            result = api_open({"path": str(path)})
            self.assertEqual(result["name"], "manifest.json")
            self.assertEqual(result["document"]["manifest_version"], "0.2")

    def test_a_file_that_is_not_json_says_so_rather_than_crashing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.json"
            path.write_text("this is not json", encoding="utf-8")
            with self.assertRaises(ApiError) as caught:
                api_open({"path": str(path)})
            self.assertIn("not valid JSON", str(caught.exception))

    def test_browsing_can_offer_files_as_well_as_folders(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sub").mkdir()
            (root / "manifest.json").write_text("{}", encoding="utf-8")
            (root / "notes.txt").write_text("x", encoding="utf-8")

            without = api_browse({"path": str(root)})
            self.assertEqual(without["files"], [])

            with_json = api_browse({"path": str(root), "suffix": ".json"})
            self.assertEqual([f["name"] for f in with_json["files"]], ["manifest.json"])
            self.assertEqual([d["name"] for d in with_json["directories"]], ["sub"])


if __name__ == "__main__":
    unittest.main()
