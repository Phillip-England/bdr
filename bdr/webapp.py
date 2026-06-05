"""Local web app for bdr docs and script launching."""

from __future__ import annotations

import json
import pathlib
import socketserver
import subprocess
import sys
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler

from .store import ScriptNameError, list_scripts, normalize_script_name, script_library_dir, script_path


APP_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>bdr docs</title>
    <style>
      :root {
        --bg: #efe7d8;
        --panel: rgba(255, 251, 245, 0.82);
        --panel-strong: #fffaf1;
        --ink: #1d1b19;
        --muted: #6f675b;
        --line: rgba(77, 58, 34, 0.14);
        --accent: #0d6b63;
        --accent-strong: #0a4f4a;
        --shadow: 0 18px 50px rgba(50, 35, 15, 0.12);
      }

      * { box-sizing: border-box; }

      body {
        margin: 0;
        min-height: 100vh;
        color: var(--ink);
        font-family: "Avenir Next", "Segoe UI", "Helvetica Neue", sans-serif;
        background:
          radial-gradient(circle at top left, rgba(255, 255, 255, 0.82), transparent 28rem),
          linear-gradient(180deg, #dcc8ac 0, #eadfcd 22rem, var(--bg) 100%);
      }

      code,
      pre,
      select {
        font-family: "SFMono-Regular", Menlo, Consolas, monospace;
      }

      .shell {
        max-width: 94rem;
        margin: 0 auto;
        padding: 1.25rem;
      }

      .hero-card {
        position: relative;
        overflow: hidden;
        margin-bottom: 1rem;
        border: 1px solid rgba(255, 255, 255, 0.45);
        border-radius: 1.6rem;
        padding: 1.3rem;
        background:
          linear-gradient(135deg, rgba(11, 65, 61, 0.95), rgba(37, 104, 97, 0.88)),
          linear-gradient(180deg, rgba(255, 255, 255, 0.08), transparent);
        color: #f8f6f1;
        box-shadow: var(--shadow);
      }

      .hero-card::after {
        content: "";
        position: absolute;
        inset: auto -4rem -4rem auto;
        width: 13rem;
        height: 13rem;
        border-radius: 50%;
        background: rgba(233, 246, 240, 0.12);
      }

      .eyebrow {
        display: inline-flex;
        gap: 0.4rem;
        align-items: center;
        padding: 0.3rem 0.6rem;
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.12);
        font-size: 0.78rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }

      h1, h2, p { margin: 0; }

      h1 {
        margin-top: 0.9rem;
        max-width: 42rem;
        font-size: clamp(2rem, 4vw, 3.4rem);
        line-height: 0.95;
      }

      .hero-copy {
        margin-top: 0.9rem;
        max-width: 42rem;
        color: rgba(248, 246, 241, 0.88);
        font-size: 1.03rem;
        line-height: 1.6;
      }

      .hero-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 0.85rem;
        margin-top: 1rem;
      }

      .hero-metric {
        padding: 0.9rem 1rem;
        border-radius: 1rem;
        background: rgba(255, 255, 255, 0.09);
        backdrop-filter: blur(8px);
      }

      .hero-metric strong {
        display: block;
        font-size: 0.78rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: rgba(255, 255, 255, 0.72);
      }

      .hero-metric span {
        display: block;
        margin-top: 0.35rem;
        font-size: 1rem;
      }

      .layout {
        display: grid;
        grid-template-columns: minmax(20rem, 24rem) minmax(0, 1fr);
        gap: 1rem;
      }

      .panel {
        border: 1px solid var(--line);
        border-radius: 1.4rem;
        background: var(--panel);
        box-shadow: var(--shadow);
        backdrop-filter: blur(12px);
      }

      .sidebar,
      .docs-shell {
        padding: 1rem;
      }

      .sidebar-head,
      .doc-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 0.75rem;
      }

      .sidebar h2,
      .doc-head h2 {
        font-size: 1rem;
        letter-spacing: 0.06em;
        text-transform: uppercase;
      }

      .path,
      .selection,
      .command-card,
      .status {
        margin-top: 1rem;
        padding: 0.9rem 0.95rem;
        border-radius: 1rem;
      }

      .path {
        background: rgba(13, 107, 99, 0.08);
        color: var(--muted);
        font-size: 0.86rem;
        line-height: 1.45;
      }

      .path code {
        color: var(--ink);
        font-size: 0.84rem;
        overflow-wrap: anywhere;
      }

      .script-list {
        margin-top: 1rem;
        display: grid;
        gap: 0.6rem;
      }

      .script-btn {
        width: 100%;
        padding: 0.9rem;
        border: 1px solid transparent;
        border-radius: 1rem;
        background: rgba(255, 255, 255, 0.58);
        text-align: left;
        color: var(--ink);
        cursor: pointer;
        transition: transform 140ms ease, border-color 140ms ease, background 140ms ease;
      }

      .script-btn:hover,
      .script-btn.active {
        transform: translateY(-1px);
        border-color: rgba(13, 107, 99, 0.32);
        background: rgba(217, 238, 231, 0.88);
      }

      .script-btn strong,
      .selection strong {
        display: block;
        font-size: 0.98rem;
      }

      .script-btn span,
      .selection code,
      .command-card p {
        display: block;
        margin-top: 0.35rem;
        color: var(--muted);
        font-size: 0.83rem;
        line-height: 1.55;
      }

      select {
        width: 100%;
        padding: 0.85rem 0.95rem;
        border: 1px solid rgba(77, 58, 34, 0.16);
        border-radius: 1rem;
        background: var(--panel-strong);
        color: var(--ink);
        font-size: 0.95rem;
      }

      button {
        border: 0;
        border-radius: 999px;
        padding: 0.75rem 1rem;
        font-size: 0.92rem;
        font-weight: 600;
        cursor: pointer;
      }

      .primary {
        background: var(--accent);
        color: #f6fffd;
      }

      .primary:hover {
        background: var(--accent-strong);
      }

      .secondary {
        background: rgba(20, 20, 20, 0.08);
        color: var(--ink);
      }

      .secondary:hover {
        background: rgba(20, 20, 20, 0.13);
      }

      .status {
        background: rgba(255, 255, 255, 0.65);
        color: var(--muted);
        line-height: 1.55;
        white-space: pre-wrap;
      }

      .status.error {
        background: rgba(161, 78, 32, 0.1);
        color: #7f3711;
      }

      .command-card {
        background: rgba(13, 107, 99, 0.08);
      }

      .run-panel {
        margin-top: 1rem;
        padding: 1rem;
      }

      .controls {
        display: flex;
        gap: 0.65rem;
        flex-wrap: wrap;
        margin-top: 0.9rem;
      }

      .inline {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        color: var(--muted);
        font-size: 0.9rem;
      }

      pre.run-output {
        min-height: 16rem;
        margin: 0.9rem 0 0;
        padding: 0.95rem;
        overflow-x: auto;
        border: 1px solid var(--line);
        border-radius: 1rem;
        background: #fffdf9;
        line-height: 1.45;
        white-space: pre-wrap;
      }

      .docs-frame {
        width: 100%;
        min-height: 78vh;
        margin-top: 0.9rem;
        border: 1px solid var(--line);
        border-radius: 1rem;
        background: #fffdf9;
      }

      @media (max-width: 980px) {
        .layout,
        .hero-grid {
          grid-template-columns: 1fr;
        }

        .docs-frame {
          min-height: 60vh;
        }
      }
    </style>
  </head>
  <body>
    <div class="shell">
      <section class="hero-card">
        <div class="eyebrow">Local bdr docs</div>
        <h1>Project docs in the browser, with one-click launches for scripts already in your main zone.</h1>
        <p class="hero-copy">
          The web UI is docs-first. Use the CLI to teleport scripts into the main zone, then launch those saved
          scripts directly from this page.
        </p>
        <div class="hero-grid">
          <div class="hero-metric">
            <strong>Command</strong>
            <span><code>bdr docs</code></span>
          </div>
          <div class="hero-metric">
            <strong>Main Zone</strong>
            <span id="hero-library">Loading...</span>
          </div>
          <div class="hero-metric">
            <strong>Workflow</strong>
            <span>Read docs, teleport, launch</span>
          </div>
        </div>
      </section>

      <section class="layout">
        <aside class="panel sidebar">
          <div class="sidebar-head">
            <h2>Main Zone Scripts</h2>
            <button class="secondary" id="refresh-btn">Refresh</button>
          </div>
          <div class="path">
            Stored in:
            <br>
            <code id="library-dir">Loading...</code>
          </div>
          <div class="script-list" id="script-list"></div>
          <div class="selection">
            <strong id="selected-script">No script selected</strong>
            <code id="current-file">Select a script from the list to enable launch.</code>
          </div>
          <div class="command-card">
            <strong>Teleport with CLI</strong>
            <p><code>bdr teleport ./flows/login.bdr</code></p>
            <p>Use the CLI to move scripts into this main zone. The web app does not create or save scripts.</p>
          </div>

          <section class="panel run-panel">
            <div class="doc-head">
              <h2>Launch</h2>
            </div>
            <div class="controls">
              <select id="browser">
                <option value="chromium">chromium</option>
                <option value="firefox">firefox</option>
                <option value="webkit">webkit</option>
              </select>
              <label class="inline">
                <input id="headless" type="checkbox">
                headless
              </label>
              <button class="primary" id="run-btn">Run Selected Script</button>
            </div>
            <div class="status" id="editor-status">Choose a script from the main zone to launch it.</div>
            <pre class="run-output" id="run-output">Run output will appear here.</pre>
          </section>
        </aside>

        <section class="panel docs-shell">
          <div class="doc-head">
            <h2>Project Docs</h2>
          </div>
          <iframe class="docs-frame" src="/guide" title="bdr documentation"></iframe>
        </section>
      </section>
    </div>

    <script>
      const state = { currentName: "" };
      const scriptList = document.getElementById("script-list");
      const libraryDir = document.getElementById("library-dir");
      const heroLibrary = document.getElementById("hero-library");
      const selectedScript = document.getElementById("selected-script");
      const currentFile = document.getElementById("current-file");
      const editorStatus = document.getElementById("editor-status");
      const runOutput = document.getElementById("run-output");

      function setStatus(message, isError = false) {
        editorStatus.textContent = message;
        editorStatus.classList.toggle("error", isError);
      }

      async function fetchJson(url, options = {}) {
        const response = await fetch(url, options);
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.error || "Request failed");
        }
        return payload;
      }

      function renderScripts(scripts) {
        scriptList.innerHTML = "";
        if (!scripts.length) {
          const empty = document.createElement("div");
          empty.className = "path";
          empty.textContent = "No scripts are in the main zone yet. Teleport one in with bdr teleport.";
          scriptList.appendChild(empty);
          return;
        }

        for (const script of scripts) {
          const button = document.createElement("button");
          button.className = "script-btn";
          if (script.name === state.currentName) {
            button.classList.add("active");
          }
          button.innerHTML = `<strong>${script.name}</strong><span>${script.size} bytes</span>`;
          button.addEventListener("click", () => selectScript(script));
          scriptList.appendChild(button);
        }
      }

      function selectScript(script) {
        state.currentName = script.name;
        selectedScript.textContent = `${script.name}.bdr`;
        currentFile.textContent = script.path;
        setStatus(`Selected ${script.name}.bdr`);
        renderScripts(window.__scripts || []);
      }

      async function refreshScripts() {
        const payload = await fetchJson("/api/scripts");
        window.__scripts = payload.scripts;
        libraryDir.textContent = payload.library_dir;
        heroLibrary.textContent = payload.library_dir;
        renderScripts(payload.scripts);

        if (state.currentName) {
          const match = payload.scripts.find((script) => script.name === state.currentName);
          if (match) {
            currentFile.textContent = match.path;
          }
        }

        return payload;
      }

      async function runScript() {
        const targetName = state.currentName.trim();
        if (!targetName) {
          setStatus("Choose a script from the main zone before running.", true);
          return;
        }

        runOutput.textContent = "Running...";
        const payload = await fetchJson("/api/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: targetName,
            browser: document.getElementById("browser").value,
            headless: document.getElementById("headless").checked,
          }),
        });

        runOutput.textContent = payload.output || "(no output)";
        if (payload.returncode === 0) {
          setStatus(`Run finished successfully for ${payload.name}.bdr`);
        } else {
          setStatus(`Run failed for ${payload.name}.bdr`, true);
        }
      }

      function showError(error) {
        const message = error instanceof Error ? error.message : String(error);
        setStatus(message, true);
      }

      document.getElementById("refresh-btn").addEventListener("click", () => refreshScripts().catch(showError));
      document.getElementById("run-btn").addEventListener("click", () => runScript().catch(showError));

      refreshScripts()
        .then((payload) => {
          if (payload.scripts.length) {
            selectScript(payload.scripts[0]);
          }
        })
        .catch(showError);
    </script>
  </body>
</html>
"""


def _cli_command_prefix() -> list[str]:
    """Build a command prefix that can invoke this same bdr CLI."""
    if getattr(sys, "frozen", False):
        return [sys.executable]

    argv0 = pathlib.Path(sys.argv[0]).name
    if argv0 == "bdr":
        return [sys.argv[0]]

    return [sys.executable, "-m", "bdr"]


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _text_response(handler: BaseHTTPRequestHandler, status: int, body: str, content_type: str) -> None:
    data = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


class _ThreadingServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _guide_html() -> str:
    """Load the project docs HTML shown inside the local web app."""
    guide_path = pathlib.Path(__file__).resolve().parent.parent / "README.html"
    if guide_path.exists():
        return guide_path.read_text(encoding="utf-8")
    return """<!doctype html><html lang="en"><body><p>README.html is missing. Open README.md in the project root.</p></body></html>"""


def _make_handler() -> type[BaseHTTPRequestHandler]:
    class DocsHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/":
                _text_response(self, HTTPStatus.OK, APP_HTML, "text/html; charset=utf-8")
                return

            if parsed.path == "/guide":
                _text_response(self, HTTPStatus.OK, _guide_html(), "text/html; charset=utf-8")
                return

            if parsed.path == "/api/scripts":
                scripts = [
                    {
                        "name": item.name,
                        "path": str(item.path),
                        "size": item.size,
                        "updated_at": item.updated_at,
                    }
                    for item in list_scripts()
                ]
                _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "library_dir": str(script_library_dir()),
                        "scripts": scripts,
                    },
                )
                return

            _json_response(self, HTTPStatus.NOT_FOUND, {"error": "Not found"})

        def do_POST(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            raw = self.rfile.read(length)

            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Request body must be valid JSON."})
                return

            if parsed.path == "/api/run":
                self._run(payload)
                return

            _json_response(self, HTTPStatus.NOT_FOUND, {"error": "Not found"})

        def _run(self, payload: dict) -> None:
            name = payload.get("name", "")
            browser = payload.get("browser", "chromium")
            headless = bool(payload.get("headless", False))

            try:
                normalized = normalize_script_name(name)
                target = script_path(normalized)
            except ScriptNameError as exc:
                _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return

            if not target.exists():
                _json_response(self, HTTPStatus.NOT_FOUND, {"error": f"Managed script not found: {normalized}"})
                return

            cmd = _cli_command_prefix() + ["run", str(target), "--browser", str(browser)]
            if headless:
                cmd.append("--headless")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
            output = (result.stdout or "") + (result.stderr or "")

            _json_response(
                self,
                HTTPStatus.OK,
                {
                    "name": normalized,
                    "returncode": result.returncode,
                    "output": output.strip(),
                },
            )

    return DocsHandler


def serve_docs_app(host: str = "127.0.0.1", port: int = 0, open_browser: bool = True) -> None:
    """Start the local docs app and serve until interrupted."""
    handler = _make_handler()
    with _ThreadingServer((host, port), handler) as server:
        actual_host, actual_port = server.server_address
        url = f"http://{actual_host}:{actual_port}/"
        print(f"bdr docs: {url}")
        print(f"  script library -> {script_library_dir()}")
        print("  Press Ctrl+C to stop the server.")
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping bdr docs.")
