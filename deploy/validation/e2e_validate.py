"""End-to-end validation of a deployed studio, over HTTPS, as a browser would use it.

Standard library only, so it runs on the server itself (Ubuntu ships python3). It drives the
studio's API with a cookie session and the CSRF header, exactly like the web UI.

Phases (run_e2e.sh runs them in order, with restarts and a backup/restore in between):

  workflow       sign in, check authentication, import the manuscript, check chapters and assets,
                 AI-assisted edit with the given model, approve it, save an author revision,
                 export DOCX, EPUB and PDF, and record everything in the state file
  verify         after a restart: the book, its history, assets and exports are exactly as recorded
  marker         create a book that exists only after the backup was taken
  verify-restore after restoring that backup: the recorded book is intact and the marker book is gone

The state file holds the session cookie: it is written with mode 0600 and deleted by run_e2e.sh.
"""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

RESULTS: list[tuple[str, bool, str]] = []


class Fail(Exception):
    pass


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' ({detail})' if detail else ''}", flush=True)
    if not ok:
        raise Fail(name)


class Client:
    def __init__(self, base: str, cafile: str | None, insecure: bool, jar_path: Path | None = None) -> None:
        if not base.startswith(("https://", "http://")):
            raise Fail("--url must start with https://")
        self.base = base.rstrip("/")
        ctx = ssl.create_default_context(cafile=cafile)
        if insecure:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        self.jar = http.cookiejar.MozillaCookieJar(str(jar_path)) if jar_path else http.cookiejar.MozillaCookieJar()
        if jar_path and jar_path.exists():
            self.jar.load(ignore_discard=True, ignore_expires=True)
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ctx), urllib.request.HTTPCookieProcessor(self.jar)
        )
        self.csrf: str | None = None
        self.origin = self.base

    def request(
        self, method: str, path: str, body: Any = None, *, raw: bytes | None = None, ctype: str | None = None,
        csrf: str | None = "session", timeout: float = 120,
    ) -> tuple[int, bytes, dict[str, str]]:  # fmt: skip
        data = raw
        headers = {"Origin": self.origin, "Accept": "application/json"}
        if body is not None:
            data, ctype = json.dumps(body).encode(), "application/json"
        if ctype:
            headers["Content-Type"] = ctype
        if method in ("POST", "PUT", "PATCH", "DELETE") and csrf is not None:
            token = self.csrf if csrf == "session" else csrf
            if token:
                headers["X-PBS-CSRF"] = token
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)  # noqa: S310 - https/http only (checked in __init__)
        try:
            with self.opener.open(req, timeout=timeout) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def json(self, method: str, path: str, body: Any = None, expect: int | tuple[int, ...] = 200, **kw: Any) -> Any:
        status, data, _ = self.request(method, path, body, **kw)
        want = expect if isinstance(expect, tuple) else (expect,)
        if status not in want:
            raise Fail(f"{method} {path} returned {status}: {data[:400].decode('utf-8', 'replace')}")
        return json.loads(data) if data else None

    def sign_in(self, username: str, password: str, setup_code: str | None) -> dict[str, Any]:
        state = self.json("GET", "/api/auth/state")
        if state["signed_in"]:
            self.csrf = state["csrf_token"]
            return dict(state)
        if state["setup_required"]:
            if not setup_code:
                raise Fail("the studio has no account yet: pass --setup-code-file")
            state = self.json("POST", "/api/auth/setup",
                              {"username": username, "password": password, "setup_code": setup_code}, csrf="1")  # fmt: skip
        else:
            state = self.json("POST", "/api/auth/login", {"username": username, "password": password}, csrf="1")
        self.csrf = state["csrf_token"]
        return dict(state)

    def save_jar(self) -> None:
        if self.jar.filename:
            self.jar.save(ignore_discard=True, ignore_expires=True)
            os.chmod(self.jar.filename, 0o600)


def multipart(fields: dict[str, str], file_field: str, file_name: str, data: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    out = b""
    for k, v in fields.items():
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    out += (f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{file_name}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n").encode() + data + b"\r\n"  # fmt: skip
    out += f"--{boundary}--\r\n".encode()
    return out, f"multipart/form-data; boundary={boundary}"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def poll(c: Client, path: str, done: tuple[str, ...], timeout_s: int, what: str) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    while True:
        cur = c.json("GET", path)
        if cur["status"] in done:
            return dict(cur)
        if time.time() > deadline:
            raise Fail(f"{what} still {cur['status']} after {timeout_s}s")
        time.sleep(2)


def snapshot(c: Client, pid: str) -> dict[str, Any]:
    """Everything that must survive: chapters, every revision's hash, head text, assets, exports."""
    chapters = c.json("GET", f"/api/projects/{pid}/chapters")
    snap: dict[str, Any] = {"chapters": {}, "assets": {}, "publications": {}}
    for ch in chapters:
        revs = c.json("GET", f"/api/projects/{pid}/chapters/{ch['id']}/revisions")
        content = c.json("GET", f"/api/projects/{pid}/chapters/{ch['id']}/content")
        snap["chapters"][ch["id"]] = {
            "title": ch["title"],
            "revisions": [[r["revision_no"], r["origin"], r["content_hash"]] for r in revs],
            "head_sha": sha(content["source_md"].encode()),
        }
    for a in c.json("GET", f"/api/projects/{pid}/assets"):
        status, data, _ = c.request("GET", f"/api/projects/{pid}/assets/{a['short_hash']}")
        snap["assets"][a["short_hash"]] = sha(data) if status == 200 else f"HTTP {status}"
    for p in c.json("GET", f"/api/projects/{pid}/publishing/publications"):
        if p["status"] == "succeeded" and p["kind"] in ("docx", "epub", "pdf"):
            status, data, _ = c.request("GET", f"/api/projects/{pid}/publishing/publications/{p['id']}/file")
            snap["publications"][p["id"]] = [p["kind"], sha(data) if status == 200 else f"HTTP {status}"]
    return snap


# ---------------------------------------------------------------- phases


def phase_workflow(c: Client, a: argparse.Namespace, state: dict[str, Any]) -> None:
    # 9. Authentication and authorised access (checked first, with a fresh client).
    anon = Client(a.url, a.cafile, a.insecure)
    status, _, _ = anon.request("GET", "/api/projects")
    check("unauthenticated API request is refused", status == 401, f"HTTP {status}")
    status, _, _ = anon.request("POST", "/api/auth/login", {"username": a.username, "password": "wrong password!!"},
                                csrf="1")  # fmt: skip
    check("wrong password is refused", status == 401, f"HTTP {status}")
    code = (
        Path(a.setup_code_file).read_text().strip() if a.setup_code_file and Path(a.setup_code_file).exists() else None
    )
    st = c.sign_in(a.username, a.password, code)
    check("signed in over HTTPS", st["signed_in"] and st["deployment"] == "server", st.get("username") or "")
    status, _, _ = c.request("POST", "/api/projects", {"title": "x", "project_type": "fiction"}, csrf=None)
    check("a write without the CSRF token is refused", status == 403, f"HTTP {status}")

    # 1. Import an existing book.
    data = Path(a.manuscript).read_bytes()
    body, ctype = multipart({}, "file", Path(a.manuscript).name, data)
    imp = c.json("POST", "/api/imports", raw=body, ctype=ctype, expect=201)
    check("manuscript uploaded and parsed", imp["status"] == "preview_ready", f"{len(imp['chapters'])} chapters found")
    status, orig, _ = c.request("GET", f"/api/imports/{imp['id']}/original")
    check("original stored byte for byte", status == 200 and sha(orig) == sha(data), sha(data)[:16])
    title = f"Validation {time.strftime('%Y-%m-%d %H:%M:%S')}"
    out = c.json("POST", f"/api/imports/{imp['id']}/commit",
                 {"mode": "new_project", "project_title": title, "project_type": "fiction"})  # fmt: skip
    pid = out["project_id"]
    state.update(project_id=pid, project_title=title)

    # 2. Chapter structure and assets.
    chapters = c.json("GET", f"/api/projects/{pid}/chapters")
    titles = [ch["title"] for ch in chapters]
    check("three chapters in order", titles == ["The Arrival", "The Inventory", "The Light"], ", ".join(titles))
    texts = {
        ch["id"]: c.json("GET", f"/api/projects/{pid}/chapters/{ch['id']}/content")["source_md"] for ch in chapters
    }
    joined = "\n".join(texts.values())
    check("table, lists and emphasis kept", "| Item" in joined and "- Weather" in joined and "**exactly**" in joined)
    assets = c.json("GET", f"/api/projects/{pid}/assets")
    check("embedded image stored as an asset", len(assets) == 1, f"{len(assets)} asset(s)")
    status, img, hdr = c.request("GET", f"/api/projects/{pid}/assets/{assets[0]['short_hash']}")
    check("asset served", status == 200 and img[:8] == b"\x89PNG\r\n\x1a\n", hdr.get("Content-Type", ""))
    check("figure referenced in the chapter", f"asset:{assets[0]['short_hash']}" in joined)

    # 3. AI-assisted edit with the configured model.
    prov = c.json("POST", "/api/ai/providers", {"kind": "ollama", "base_url": a.ollama_url}, expect=201)
    test = c.json("POST", f"/api/ai/providers/{prov['id']}/test")
    check("model server connection test", bool(test["ok"]), test.get("message") or "")
    refreshed = c.json("POST", f"/api/ai/providers/{prov['id']}/models/refresh")
    names = [m["name"] for m in refreshed.get("models", [])]
    check("model available", a.model in names, ", ".join(names[:5]))
    first = chapters[0]
    cur0 = c.json("GET", f"/api/projects/{pid}/chapters/{first['id']}/content")
    head, text0 = cur0["revision_no"], cur0["source_md"]
    # Select the chapter's first paragraph, as the author would in the editor.
    para = next(p for p in text0.split("\n\n") if p.strip() and not p.lstrip().startswith(("#", "{", "!")))
    sel_start = text0.index(para)
    job = c.json("POST", f"/api/projects/{pid}/ai/jobs", {
        "chapter_id": first["id"], "task": "revise", "mode": "replace_selection", "base_revision_no": head,
        "selection_start": sel_start, "selection_end": sel_start + len(para), "provider_id": prov["id"],
        "model_name": a.model, "client_request_id": uuid.uuid4().hex,
        "instruction": "Tighten this paragraph. Keep every fact and name.",
    }, expect=202)  # fmt: skip
    job = poll(c, f"/api/ai/jobs/{job['id']}", ("succeeded", "failed", "cancelled", "interrupted"), a.ai_timeout,
               "AI job")  # fmt: skip
    check("AI job finished on the worker", job["status"] == "succeeded", job.get("error_message") or job["status"])

    # 4. Review and approve.
    props = [
        p for p in c.json("GET", f"/api/projects/{pid}/proposals?chapter_id={first['id']}") if p["status"] == "pending"
    ]
    check("suggestion waiting for review (not applied by itself)", len(props) == 1)
    still = c.json("GET", f"/api/projects/{pid}/chapters/{first['id']}/content")["revision_no"]
    check("chapter unchanged before approval", still == head)
    acc = c.json("POST", f"/api/projects/{pid}/proposals/{props[0]['id']}/accept", {"expected_head_no": head})
    check("suggestion approved", acc is not None)

    # 5. Save a new manuscript revision (the author's own edit on top).
    cur = c.json("GET", f"/api/projects/{pid}/chapters/{first['id']}/content")
    edited = cur["source_md"].rstrip() + "\n\nThe author added this line after reviewing the suggestion.\n"
    saved = c.json("PUT", f"/api/projects/{pid}/chapters/{first['id']}/content",
                   {"source_md": edited, "expected_head_no": cur["revision_no"]})  # fmt: skip
    revs = c.json("GET", f"/api/projects/{pid}/chapters/{first['id']}/revisions")
    origins = [r["origin"] for r in sorted(revs, key=lambda r: r["revision_no"])]
    check("history: imported, AI, author", len(revs) == 3 and origins[0] == "imported" and origins[-1] == "human"
          and origins[1] in ("ai_generated", "ai_assisted"), " -> ".join(origins))  # fmt: skip
    check("new revision is the head", saved["revision_no"] == revs[-1]["revision_no"] if "revision_no" in saved
          else True)  # fmt: skip

    # 6. Export DOCX, EPUB and PDF (a background task in the worker).
    task = c.json(
        "POST", f"/api/projects/{pid}/publishing/build-task", {"formats": ["docx", "epub", "pdf"]}, expect=202
    )
    task = poll(c, f"/api/tasks/{task['id']}", ("succeeded", "failed", "interrupted"), 900, "export task")
    check("export task finished on the worker", task["status"] == "succeeded", task.get("error_message") or "")
    magic = {"docx": b"PK", "epub": b"PK", "pdf": b"%PDF"}
    report = {}
    for pub in task["result"]["publications"]:
        status, data, _ = c.request("GET", f"/api/projects/{pid}/publishing/publications/{pub['id']}/file")
        check(f"{pub['kind'].upper()} downloaded", status == 200 and data.startswith(magic[pub["kind"]]),
              f"{len(data)} bytes, {pub.get('page_count') or '-'} pages")  # fmt: skip
        report[pub["kind"]] = pub.get("report_summary")
    state["preflight"] = report  # recorded as-is: preflight findings, not a compliance verdict
    state["warnings"] = task["result"].get("warnings", [])
    state["snapshot"] = snapshot(c, pid)


def phase_verify(c: Client, a: argparse.Namespace, state: dict[str, Any], label: str) -> None:
    st = c.json("GET", "/api/auth/state")
    if st["signed_in"]:
        check(f"{label}: the browser session is still valid", True)
        c.csrf = st["csrf_token"]
    else:
        c.sign_in(a.username, a.password, None)
        check(f"{label}: signed in again", True)
    pid = state["project_id"]
    proj = c.json("GET", f"/api/projects/{pid}")
    check(f"{label}: book exists", proj["title"] == state["project_title"], proj["title"])
    now = snapshot(c, pid)
    then = state["snapshot"]
    check(f"{label}: chapters and full revision history identical", now["chapters"] == then["chapters"],
          f"{sum(len(v['revisions']) for v in now['chapters'].values())} revisions")  # fmt: skip
    check(f"{label}: assets identical", now["assets"] == then["assets"], f"{len(now['assets'])} asset(s)")
    check(f"{label}: exported files identical", now["publications"] == then["publications"],
          f"{len(now['publications'])} files")  # fmt: skip


def phase_marker(c: Client, a: argparse.Namespace, state: dict[str, Any]) -> None:
    c.sign_in(a.username, a.password, None)
    p = c.json("POST", "/api/projects", {"title": "Created after the backup", "project_type": "fiction"}, expect=201)
    state["marker_id"] = p["id"]
    check("marker book created after the backup", True, p["id"])


def phase_verify_restore(c: Client, a: argparse.Namespace, state: dict[str, Any]) -> None:
    phase_verify(c, a, state, "after restore")
    status, _, _ = c.request("GET", f"/api/projects/{state['marker_id']}")
    check("after restore: the book created after the backup is gone", status == 404, f"HTTP {status}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("phase", choices=["workflow", "verify", "marker", "verify-restore"])
    ap.add_argument("--url", required=True)
    ap.add_argument("--username", required=True)
    ap.add_argument("--password-file", required=True)
    ap.add_argument("--setup-code-file")
    ap.add_argument("--cafile")
    ap.add_argument("--insecure", action="store_true")
    ap.add_argument("--manuscript")
    ap.add_argument("--ollama-url", default="http://ollama:11434")
    ap.add_argument("--model", default="qwen2.5:0.5b")
    ap.add_argument("--ai-timeout", type=int, default=1800)
    ap.add_argument("--state", required=True)
    ap.add_argument("--label", default="after restart")
    a = ap.parse_args()
    a.password = Path(a.password_file).read_text().strip()
    state_path = Path(a.state)
    state: dict[str, Any] = json.loads(state_path.read_text()) if state_path.exists() else {}
    c = Client(a.url, a.cafile, a.insecure, state_path.with_suffix(".cookies"))
    try:
        if a.phase == "workflow":
            phase_workflow(c, a, state)
        elif a.phase == "verify":
            phase_verify(c, a, state, a.label)
        elif a.phase == "marker":
            phase_marker(c, a, state)
        else:
            phase_verify_restore(c, a, state)
    except Fail as exc:
        print(f"STOPPED: {exc}", file=sys.stderr)
        return 1
    finally:
        c.save_jar()
        state_path.write_text(json.dumps(state, indent=2))
        os.chmod(state_path, 0o600)
    print(f"phase {a.phase}: {sum(ok for _, ok, _ in RESULTS)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
