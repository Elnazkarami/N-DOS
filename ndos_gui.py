#!/usr/bin/env python3
"""Serve the N-DOS interface on this machine.

A browser page cannot read a drive or run a scan. So the interface is served
by a small local server that calls the same functions the command line does —
one implementation of the standard, not two.

    ndos gui

That starts a server on localhost, prints a URL and opens it. Nothing is
exposed to the network and nothing leaves the machine.

Standard library only, like the rest of NDOS: the interface is shipped already
built, so running it needs no Node, no npm and no install beyond the package.

Security
--------
This serves a program that can read any path you point it at, so it is treated
as what it is. The server binds to the loopback address only, requires a token
generated at startup and known only to the page it opened, checks that requests
claim a local Host, and refuses requests carrying an Origin header from
anywhere else — which is what stops a web page you happen to have open from
talking to it.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import secrets
import socket
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

import ndos_query
import ndos_report
import ndos_scan
import ndos_table
import ndos_validate

GUI_VERSION = "0.1.0"

def _static_root() -> Path:
    """Where the built interface lives.

    It ships as a package rather than a loose directory because a wheel only
    carries files that belong to one: installed from PyPI, a loose directory
    would simply not arrive.
    """
    try:
        import ndos_gui_static

        return ndos_gui_static.ROOT
    except Exception:
        return Path(__file__).resolve().parent / "ndos_gui_static"


STATIC_ROOT = _static_root()

#: Hosts a request may claim to be for. Anything else is someone else's.
LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}

#: Long-running work, by job id.
JOBS: Dict[str, Dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()


class ApiError(Exception):
    """Something the caller asked for that cannot be done."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> str:
    return ndos_scan._utc_iso(datetime.now(tz=timezone.utc).timestamp())


# --------------------------------------------------------------------------
# jobs
# --------------------------------------------------------------------------

def start_job(kind: str, work: Callable[[Callable[[Dict[str, Any]], None]], Any]) -> str:
    """Run something slow in the background and let the page watch it.

    A checksummed scan of a lab drive can take hours. Doing that inside a
    request would look to the browser like the program had died.
    """
    job_id = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "kind": kind,
            "state": "running",
            "started_at": _now(),
            "progress": {},
            "result": None,
            "error": None,
        }

    def report(update: Dict[str, Any]) -> None:
        with JOBS_LOCK:
            JOBS[job_id]["progress"] = update

    def run() -> None:
        try:
            result = work(report)
            with JOBS_LOCK:
                JOBS[job_id].update(state="done", result=result, ended_at=_now())
        except Exception as error:  # a job must never take the server with it
            with JOBS_LOCK:
                JOBS[job_id].update(
                    state="failed",
                    error=f"{type(error).__name__}: {error}",
                    ended_at=_now(),
                )

    threading.Thread(target=run, daemon=True).start()
    return job_id


def job_state(job_id: str) -> Dict[str, Any]:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            raise ApiError(f"no such job: {job_id}", 404)
        return dict(job)


# --------------------------------------------------------------------------
# api
# --------------------------------------------------------------------------

def _path_argument(payload: Dict[str, Any], key: str = "path") -> Path:
    raw = payload.get(key)
    if not raw or not isinstance(raw, str):
        raise ApiError(f"missing {key}")
    path = Path(raw).expanduser()
    if not path.exists():
        raise ApiError(f"no such path: {path}", 404)
    # Everything reached through here works on a directory. Without this the
    # failure surfaced as a 500 and the page showed the words "ValueError" to
    # someone who had simply picked the wrong thing.
    if not path.is_dir():
        raise ApiError(f"that is a file, not a folder: {path}")
    return path


def api_status(_: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "gui_version": GUI_VERSION,
        "spec_version": ndos_validate.SPEC_VERSION,
        "home": str(Path.home()),
        "cwd": str(Path.cwd()),
        "interface_built": STATIC_ROOT.is_dir(),
    }


def api_browse(payload: Dict[str, Any]) -> Dict[str, Any]:
    """List a directory, so the page can offer a folder picker.

    A browser will not hand a program a filesystem path, so the choosing has
    to happen on this side.
    """
    raw = payload.get("path") or str(Path.home())
    path = Path(raw).expanduser()
    if not path.is_dir():
        raise ApiError(f"not a directory: {path}", 404)

    # A suffix asks for the files of that kind as well, so the same picker can
    # choose a manifest.json as easily as a folder.
    suffix = payload.get("suffix")
    wanted = str(suffix).lower() if suffix else None

    directories: List[Dict[str, Any]] = []
    matches: List[Dict[str, Any]] = []
    files = 0
    try:
        for entry in sorted(path.iterdir(), key=lambda p: p.name.lower()):
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                directories.append({"name": entry.name, "path": str(entry)})
                continue
            files += 1
            if wanted and entry.name.lower().endswith(wanted):
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = 0
                matches.append(
                    {"name": entry.name, "path": str(entry), "bytes": size}
                )
    except PermissionError:
        raise ApiError(f"not readable: {path}", 403)

    parent = str(path.parent) if path.parent != path else None
    return {
        "path": str(path),
        "parent": parent,
        "directories": directories,
        "files": matches,
        "file_count": files,
        "is_project": all(
            (path / name).is_dir()
            for name in ("raw_data", "processed_data", "metadata")
        ),
    }


def api_estimate(payload: Dict[str, Any]) -> Dict[str, Any]:
    """How long a checksummed scan would take, measured on this drive."""
    return ndos_scan.estimate(_path_argument(payload))


def api_report(payload: Dict[str, Any]) -> Dict[str, Any]:
    path = _path_argument(payload)
    manifest = ndos_scan.scan(
        path, include_checksums=bool(payload.get("checksums")), progress=False
    )
    return ndos_report.build_report(manifest)


def api_validate(payload: Dict[str, Any]) -> Dict[str, Any]:
    return ndos_validate.validate(_path_argument(payload))


def api_scan(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Start a scan in the background and return the job watching it."""
    path = _path_argument(payload)
    checksums = bool(payload.get("checksums"))
    cache = payload.get("cache")
    cache_path = Path(cache).expanduser() if cache else None

    def work(report: Callable[[Dict[str, Any]], None]) -> Dict[str, Any]:
        manifest = ndos_scan.scan(
            path,
            include_checksums=checksums,
            progress=False,
            cache_path=cache_path,
            on_progress=report,
        )
        return ndos_report.build_report(manifest)

    return {"job": start_job("scan", work)}


def api_job(payload: Dict[str, Any]) -> Dict[str, Any]:
    job = payload.get("job")
    if not job:
        raise ApiError("missing job")
    return job_state(str(job))


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise ApiError(f"not a file: {path}", 404)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ApiError(f"{path.name} is not valid JSON: {error}")
    except OSError as error:
        raise ApiError(f"could not read {path.name}: {error}", 403)
    if not isinstance(loaded, dict):
        raise ApiError(f"{path.name} does not hold an NDOS document")
    return loaded


def api_open(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Read a JSON document the user picked, so nothing has to be dragged.

    The page could already read a file the user dropped on it. It could not
    read one by name, which is how people actually refer to their files.
    """
    raw = payload.get("path")
    if not raw or not isinstance(raw, str):
        raise ApiError("missing path")
    path = Path(raw).expanduser()
    return {"path": str(path), "name": path.name, "document": _read_json(path)}


def api_link(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Link a project's metadata tables, without writing anything.

    `ndos table check --emit` writes the linked records to a file. Nothing
    here needs that file to exist: the same function builds the records in
    memory, so a project can be queried without first being written to.
    """
    path = _path_argument(payload)
    # Either the metadata directory itself or the project holding it: a person
    # picking a folder picks the project, and being told to pick the one inside
    # it is the sort of thing a program should work out for itself.
    if not (path / ndos_table.SESSIONS_FILE).is_file():
        inner = path / "metadata"
        if (inner / ndos_table.SESSIONS_FILE).is_file():
            path = inner
        else:
            raise ApiError(
                f"no metadata tables under {path}. "
                f"`ndos table export` writes them from a scan."
            )
    return ndos_table.link_records(
        path, include_empty=bool(payload.get("include_empty", True))
    )


def api_check(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Check a project's metadata tables, the way `ndos table check` does.

    The entry form can only judge one value at a time: it knows `F` is a sex
    and `mouse` is a species. It cannot know that a procedure names an animal
    the animal table has never heard of, because that answer lives across
    three files. This does.
    """
    path = _path_argument(payload)
    if not (path / ndos_table.SESSIONS_FILE).is_file():
        inner = path / "metadata"
        if (inner / ndos_table.SESSIONS_FILE).is_file():
            path = inner
        else:
            raise ApiError(
                f"no metadata tables under {path}. "
                f"`ndos table export` writes them from a scan."
            )
    result = ndos_table.check_metadata(path)
    result["directory"] = str(path)
    return result


def api_query(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Run a cohort query, and answer with all three outcomes.

    The page used to filter rows itself, by comparing strings. That quietly
    turned "this session never recorded a species" into "this session is not
    a mouse", which is the one mistake this whole tool exists to prevent. The
    query runs here instead, against the same code the command line uses, so
    a session that cannot be ruled out is reported as exactly that.
    """
    metadata = payload.get("metadata")
    if metadata is None:
        source = payload.get("path")
        if not source or not isinstance(source, str):
            raise ApiError("missing metadata or path")
        candidate = Path(source).expanduser()
        metadata = (
            api_link({"path": source})
            if candidate.is_dir()
            else _read_json(candidate)
        )
    if not isinstance(metadata, dict):
        raise ApiError("metadata must be a linked-records document")

    raw = payload.get("constraints") or []
    if not isinstance(raw, list):
        raise ApiError("constraints must be a list of 'field=value' strings")

    constraints = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            continue
        try:
            constraints.append(ndos_query.parse_constraint(item))
        except ndos_query.QueryError as error:
            raise ApiError(str(error))

    result = ndos_query.run_query(metadata, constraints)
    # The command line prints these; the page had no way to see them.
    result["diagnosis"] = ndos_query.diagnose(result)
    return result


#: What the page may ask for. Anything not here does not exist.
ROUTES: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "status": api_status,
    "browse": api_browse,
    "estimate": api_estimate,
    "report": api_report,
    "validate": api_validate,
    "scan": api_scan,
    "job": api_job,
    "open": api_open,
    "link": api_link,
    "check": api_check,
    "query": api_query,
}


# --------------------------------------------------------------------------
# server
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = f"ndos-gui/{GUI_VERSION}"
    token = ""

    def log_message(self, fmt: str, *args: Any) -> None:
        # The default logs every request to stderr, which buries the one line
        # the user actually needs: the URL to open.
        pass

    # -- guards ---------------------------------------------------------
    def _local_host(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        return host in LOCAL_HOSTS

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if origin is None:
            return True  # not a browser cross-origin request
        host = urlparse(origin).hostname or ""
        return host in LOCAL_HOSTS

    def _authorised(self, query: Dict[str, List[str]]) -> bool:
        supplied = self.headers.get("X-NDOS-Token") or (query.get("token") or [""])[0]
        return secrets.compare_digest(supplied, self.token)

    # -- replies --------------------------------------------------------
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: Dict[str, Any]) -> None:
        self._send(
            status,
            json.dumps(payload).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    # -- handlers -------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if not self._local_host() or not self._same_origin():
            self._json(403, {"error": "this server answers only to this machine"})
            return

        if parsed.path.startswith("/api/"):
            if not self._authorised(query):
                self._json(403, {"error": "missing or wrong token"})
                return
            name = parsed.path[len("/api/"):]
            payload = {key: values[0] for key, values in query.items()}
            self._dispatch(name, payload)
            return

        self._serve_static(unquote(parsed.path), query)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if not self._local_host() or not self._same_origin():
            self._json(403, {"error": "this server answers only to this machine"})
            return
        if not parsed.path.startswith("/api/"):
            self._json(404, {"error": "not found"})
            return
        if not self._authorised(query):
            self._json(403, {"error": "missing or wrong token"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "body was not JSON"})
            return
        if not isinstance(payload, dict):
            self._json(400, {"error": "body must be an object"})
            return

        self._dispatch(parsed.path[len("/api/"):], payload)

    def _dispatch(self, name: str, payload: Dict[str, Any]) -> None:
        handler = ROUTES.get(name)
        if handler is None:
            self._json(404, {"error": f"no such endpoint: {name}"})
            return
        try:
            self._json(200, handler(payload))
        except ApiError as error:
            self._json(error.status, {"error": str(error)})
        except Exception as error:
            # Surface the reason rather than a blank 500; this runs on the
            # user's own machine, and a stack trace they can paste into an
            # issue is worth more than a tidy error page.
            self._json(
                500,
                {
                    "error": f"{type(error).__name__}: {error}",
                    "traceback": traceback.format_exc(limit=6),
                },
            )

    def _serve_static(self, path: str, query: Dict[str, List[str]]) -> None:
        if not STATIC_ROOT.is_dir():
            self._send(
                503,
                _not_built_page().encode("utf-8"),
                "text/html; charset=utf-8",
            )
            return

        relative = path.lstrip("/") or "index.html"
        target = (STATIC_ROOT / relative).resolve()
        try:
            target.relative_to(STATIC_ROOT)
        except ValueError:
            self._json(403, {"error": "outside the interface directory"})
            return

        if not target.is_file():
            # A single-page interface owns its own routing.
            target = STATIC_ROOT / "index.html"
            if not target.is_file():
                self._json(404, {"error": "not found"})
                return

        body = target.read_bytes()
        if target.name == "index.html":
            body = body.replace(
                b"</head>",
                (
                    '<script>window.__NDOS__={token:"%s",version:"%s"};</script></head>'
                    % (self.token, GUI_VERSION)
                ).encode("utf-8"),
                1,
            )
        kind, _ = mimetypes.guess_type(target.name)
        self._send(200, body, kind or "application/octet-stream")


def _not_built_page() -> str:
    return f"""<!doctype html>
<meta charset="utf-8">
<title>N-DOS — interface not built</title>
<style>
 body {{ font: 15px/1.6 ui-sans-serif, system-ui, sans-serif; max-width: 46em;
        margin: 4em auto; padding: 0 1.5em; color: #171b24; }}
 code {{ background: #eef0f5; padding: .15em .4em; border-radius: 3px; }}
</style>
<h1>The interface has not been built</h1>
<p>The server is running, but the built interface is not in
<code>{STATIC_ROOT}</code>.</p>
<p>A released copy of NDOS ships it already built. From a source checkout,
build it once:</p>
<pre><code>cd gui &amp;&amp; npm install &amp;&amp; npm run build\ncp -R gui/dist/. ndos_gui_static/</code></pre>
<p>Everything works from the command line meanwhile — <code>ndos --help</code>.</p>
"""


def _free_port(preferred: int) -> int:
    """The preferred port, or one the operating system picks if it is taken."""
    for candidate in (preferred, 0):
        try:
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", candidate))
                return probe.getsockname()[1]
        except OSError:
            continue
    raise ApiError("could not find a free port", 500)


def serve(
    port: int = 7373,
    open_browser: bool = True,
    token: Optional[str] = None,
) -> Tuple[ThreadingHTTPServer, str]:
    """Start the server and return it with the URL to open."""
    Handler.token = token or secrets.token_urlsafe(24)
    chosen = _free_port(port)
    httpd = ThreadingHTTPServer(("127.0.0.1", chosen), Handler)
    url = f"http://127.0.0.1:{chosen}/?token={Handler.token}"

    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    return httpd, url


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Serve the N-DOS interface on this machine.",
        epilog=(
            "Nothing is exposed to the network: the server binds to the "
            "loopback address and requires a token that only the page it "
            "opened is given."
        ),
    )
    parser.add_argument(
        "-p", "--port", type=int, default=7373,
        help="Port to serve on; another is chosen if this one is busy",
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="Do not open a browser"
    )
    args = parser.parse_args()

    httpd, url = serve(port=args.port, open_browser=not args.no_browser)
    # Flushed, because the address is the only way in: run with the output
    # redirected and a buffered banner would not appear until the server stops.
    print(f"N-DOS is running at {url}", flush=True)
    print(
        "This address works only on this machine. Press Ctrl-C to stop.",
        flush=True,
    )
    if not STATIC_ROOT.is_dir():
        print(
            f"\nThe built interface is not in {STATIC_ROOT}; the page will say "
            "how to build it.",
            file=sys.stderr,
        )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
