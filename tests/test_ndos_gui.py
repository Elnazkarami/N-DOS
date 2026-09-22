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
from ndos_gui import ApiError, api_browse, job_state, start_job

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


if __name__ == "__main__":
    unittest.main()


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
