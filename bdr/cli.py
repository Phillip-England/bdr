"""bdr CLI — entry point for the `bdr` command."""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys
from datetime import datetime

import click

from . import __version__
from .interpreter import BdrError, DEFAULT_SCREENSHOT_DIR
from .runner import check_script, run_script
from .seed import extract_seed_version, render_seed
from .status import DEFAULT_STATUS_FILE
from .store import (
    ScriptNameError,
    ensure_script_library_dir,
    import_script,
    normalize_script_name,
    script_library_dir,
    script_path,
)
from .webapp import serve_docs_app


def _fail(heading: str, body: str) -> None:
    """Print a clean, indented error to stderr and exit 1 — no traceback."""
    click.echo(f"\n{heading}\n", err=True)
    for line in body.splitlines():
        click.echo(f"  {line}", err=True)
    click.echo("", err=True)
    sys.exit(1)


@click.group()
@click.version_option(__version__, prog_name="bdr")
def main() -> None:
    """bdr — a DSL for driving browsers.

    \b
    Common commands:
      bdr run script.bdr         Execute a script
      bdr check script.bdr       Validate without running a browser
      bdr new script.bdr         Create a new script from a template
      bdr seed                   Plant/update an LLM seed file in this project
      bdr docs                   Open the local docs + script launcher web app
      bdr teleport script.bdr    Move a script into the main zone library
      bdr extract URL SELECTOR   Generate a .el selector file from a live page
      bdr setup                  Install Playwright browsers
      bdr screenshots            List captured screenshots
      bdr kill                   Kill any currently running bdr test
    """


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

@main.command()
@click.argument("script", metavar="SCRIPT.bdr")
@click.option("--browser", default="chromium", show_default=True,
              type=click.Choice(["chromium", "firefox", "webkit"]),
              help="Browser to use.")
@click.option("--headless", is_flag=True, default=False,
              help="Run without a visible browser window.")
@click.option("--slow", default=0.0, metavar="SECONDS", show_default=True,
              help="Pause between each command (useful for debugging).")
@click.option("--timeout", default=30_000, metavar="MS", show_default=True,
              help="Default element wait timeout in milliseconds.")
@click.option("--screenshot-dir", default=None, metavar="PATH",
              help=f"Where to save screenshots. Default: {DEFAULT_SCREENSHOT_DIR}")
@click.option("--no-status", is_flag=True, default=False,
              help="Disable writing the live status file for this run.")
@click.option("--status-file", default=None, metavar="PATH",
              help=f"Where to write the live status file. Default: {DEFAULT_STATUS_FILE}")
def run(script: str, browser: str, headless: bool, slow: float,
        timeout: int, screenshot_dir: str | None,
        no_status: bool, status_file: str | None) -> None:
    """Execute a .bdr script."""
    sdir = pathlib.Path(screenshot_dir).resolve() if screenshot_dir else None
    sf = pathlib.Path(status_file).resolve() if status_file else None
    try:
        run_script(
            script,
            browser=browser,
            headed=not headless,
            slow_mo=slow,
            timeout=timeout,
            screenshot_dir=sdir,
            status_file=sf,
            no_status=no_status,
        )
    except BdrError as exc:
        _fail(f"Script failed — {script}:", str(exc))
    except FileNotFoundError as exc:
        _fail("File not found:", str(exc))
    except SyntaxError as exc:
        _fail(f"Syntax error in {script}:", str(exc))
    except Exception as exc:
        _fail("Unexpected error:", str(exc))


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

@main.command()
@click.argument("script", metavar="SCRIPT.bdr")
def check(script: str) -> None:
    """Parse and validate a .bdr script without running a browser.

    Exits with code 0 if the script is valid, 1 if errors were found.
    """
    errors = check_script(script)
    if not errors:
        click.echo(f"  ok: {script}")
    else:
        for err in errors:
            click.echo(f"  error: {err}", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# new
# ---------------------------------------------------------------------------

@main.command()
@click.argument("name", metavar="SCRIPT.bdr")
def new(name: str) -> None:
    """Create a new .bdr script from a starter template."""
    dest = pathlib.Path(name)
    if dest.exists():
        raise click.ClickException(f"File already exists: {dest}")

    template = f"""\
// {dest.name}
// Created with: bdr new {dest.name}

// How long to wait for elements before failing (milliseconds).
timeout = 15000

// Pause between every action in seconds (0 = no pause).
// slow = 0.3

// Where to save screenshots — defaults to ~/.bdr/screenshots/
// screenshot_dir("./screenshots")

// Define variables.
// $url = "https://example.com"
// $user = "me@example.com"

load("https://example.com")
// load_clipboard()              // read URL from your system clipboard

// Interact with elements using CSS selector chains:
// .selector.click()
// #id.fill("value")
// .selector[0].click()       // pick the first matching element
// assert_title("Expected title")
// screenshot("result.png")

log("Script complete")
"""
    dest.write_text(template, encoding="utf-8")
    click.echo(f"  created: {dest}")


def _resolve_managed_name(initial_name: str, *, prompt_on_conflict: bool) -> str:
    """Resolve a managed script name, prompting when interactive if needed."""
    candidate = initial_name
    while True:
        try:
            normalized = normalize_script_name(candidate)
        except ScriptNameError as exc:
            if not prompt_on_conflict:
                raise click.ClickException(str(exc)) from exc
            click.echo(f"  invalid name: {exc}", err=True)
            candidate = click.prompt("  Choose a different script name")
            continue

        if script_path(normalized).exists():
            if not prompt_on_conflict:
                raise click.ClickException(
                    f"Managed script already exists: {normalized}.bdr\n"
                    "  Choose a different name with --name."
                )
            click.echo(f"  name already taken: {normalized}.bdr", err=True)
            candidate = click.prompt("  Choose a different script name")
            continue

        return normalized


# ---------------------------------------------------------------------------
# seed
# ---------------------------------------------------------------------------

@main.command()
@click.option(
    "--path",
    "seed_path",
    default="BDR_SEED.md",
    show_default=True,
    metavar="FILE",
    help="Where to write the seed file.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Rewrite the seed even when the version already matches.",
)
def seed(seed_path: str, force: bool) -> None:
    """Plant or refresh an LLM seed file with version-aware updates."""
    target = pathlib.Path(seed_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    new_content = render_seed(__version__)

    if not target.exists():
        target.write_text(new_content, encoding="utf-8")
        click.echo(f"  planted seed: {target}")
        click.echo(f"  version: {__version__}")
        return

    existing = target.read_text(encoding="utf-8")
    existing_version = extract_seed_version(existing)

    if not force and existing_version == __version__:
        click.echo(f"  seed up-to-date: {target}")
        click.echo(f"  version: {__version__}")
        return

    target.write_text(new_content, encoding="utf-8")
    if force:
        click.echo(f"  refreshed seed (forced): {target}")
        click.echo(f"  version: {__version__}")
    elif existing_version:
        click.echo(f"  updated seed: {target}")
        click.echo(f"  version: {existing_version} -> {__version__}")
    else:
        click.echo(f"  updated seed: {target}")
        click.echo(f"  version: unknown -> {__version__}")


# ---------------------------------------------------------------------------
# docs
# ---------------------------------------------------------------------------

@main.command()
@click.option("--host", default="127.0.0.1", show_default=True,
              help="Host interface to bind the local web app to.")
@click.option("--port", default=0, show_default=True, type=int,
              help="Port to bind. Use 0 to choose a free port automatically.")
@click.option("--no-open", is_flag=True, default=False,
              help="Start the server without opening a browser.")
def docs(host: str, port: int, no_open: bool) -> None:
    """Open the local docs and script launcher web app."""
    ensure_script_library_dir()
    serve_docs_app(host=host, port=port, open_browser=not no_open)


# ---------------------------------------------------------------------------
# teleport
# ---------------------------------------------------------------------------

@main.command(name="teleport")
@click.argument("source", type=click.Path(exists=True, dir_okay=False, path_type=pathlib.Path))
@click.option("--name", default=None, metavar="SCRIPT_NAME",
              help="Script name to use inside the main zone. Defaults to the source filename.")
def teleport(source: pathlib.Path, name: str | None) -> None:
    """Teleport an external .bdr file into the main zone library."""
    if source.suffix.lower() != ".bdr":
        raise click.ClickException("Only .bdr files can be teleported into the main zone.")

    ensure_script_library_dir()
    prompt_on_conflict = sys.stdin.isatty() and sys.stdout.isatty()
    requested_name = name or source.stem
    managed_name = _resolve_managed_name(requested_name, prompt_on_conflict=prompt_on_conflict)
    if source.resolve() == script_path(managed_name).resolve():
        raise click.ClickException("That script is already in the managed library.")
    target = import_script(source.resolve(), managed_name)
    errors = check_script(target)

    click.echo(f"  imported: {source}")
    click.echo(f"  stored:   {target}")
    click.echo(f"  main zone: {script_library_dir()}")
    if errors:
        click.echo("  validation:")
        for err in errors:
            click.echo(f"    - {err}")
    else:
        click.echo("  validation: ok")
    click.echo("  Open with: bdr docs")


@main.command(name="sort", hidden=True)
@click.argument("source", type=click.Path(exists=True, dir_okay=False, path_type=pathlib.Path))
@click.option("--name", default=None, metavar="SCRIPT_NAME",
              help="Managed script name to use inside the library. Defaults to the source filename.")
def sort_alias(source: pathlib.Path, name: str | None) -> None:
    """Backward-compatible alias for teleport."""
    teleport.callback(source, name)


# ---------------------------------------------------------------------------
# extract
# ---------------------------------------------------------------------------

@main.command()
@click.argument("url")
@click.argument("selector")
@click.option("--output", "-o", default=None, metavar="FILE.el",
              help="Output path. Default: derived from the selector name.")
@click.option("--browser", default="chromium", show_default=True,
              type=click.Choice(["chromium", "firefox", "webkit"]),
              help="Browser to use.")
@click.option("--headless", is_flag=True, default=False,
              help="Run without a visible browser window.")
@click.option("--timeout", default=15_000, metavar="MS", show_default=True,
              help="Page load timeout in milliseconds.")
def extract(url: str, selector: str, output: str | None,
            browser: str, headless: bool, timeout: int) -> None:
    """Inspect a live page and print the CSS selectors of its elements.

    Navigates to URL, finds SELECTOR, and writes every child element
    that has a stable CSS selector (id, name, or meaningful href) to
    a .el file for reference.

    \b
    Examples:
      bdr extract https://example.com/login "#login-form"
      bdr extract https://example.com/login "#login-form" -o selectors/login.el
      bdr extract https://example.com "form" --browser firefox
    """
    from playwright.sync_api import sync_playwright
    from .extractor import extract_elements

    # Derive a default output filename from the selector.
    if output is None:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", selector.lstrip("#.[")).strip("-")
        output = f"{slug}.el"

    out_path = pathlib.Path(output)

    click.echo(f"Extracting selectors from {url}")
    click.echo(f"  root: {selector}")

    try:
        with sync_playwright() as pw:
            browser_type = getattr(pw, browser)
            b = browser_type.launch(headless=not headless)
            page = b.new_page()
            try:
                page.goto(url, timeout=timeout)
                count = extract_elements(page, selector, out_path)
            finally:
                b.close()
    except BdrError as exc:
        _fail("Extract failed:", str(exc))
    except Exception as exc:
        from .interpreter import _humanize_playwright_error
        msg = _humanize_playwright_error("navigate", exc)
        _fail("Extract failed:", msg)

    click.echo(f"  found:  {count} selectors")
    click.echo(f"  saved:  {out_path}")
    click.echo(f"\nUse the selectors directly in your script:")
    click.echo(f"  #email.fill(\"me@example.com\")")
    click.echo(f"  #submit.click()")


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------

@main.command()
@click.option("--all-browsers", is_flag=True, default=False,
              help="Install all browsers (chromium, firefox, webkit). Default: chromium only.")
def setup(all_browsers: bool) -> None:
    """Install Playwright browsers and verify the environment.

    Run this once after installing bdr, or after upgrading Playwright.

    \b
    Examples:
      bdr setup                  # installs Chromium (default)
      bdr setup --all-browsers   # installs Chromium, Firefox, and WebKit
    """
    click.echo(f"bdr {__version__} setup")

    cmd = [sys.executable, "-m", "playwright", "install"]
    if not all_browsers:
        cmd.append("chromium")
        label = "chromium"
    else:
        label = "chromium, firefox, webkit"

    click.echo(f"Installing browsers: {label}")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        raise click.ClickException("Browser installation failed.")

    click.echo("  done. Run 'bdr run <script.bdr>' to get started.")


# ---------------------------------------------------------------------------
# screenshots
# ---------------------------------------------------------------------------

@main.command("screenshots")
@click.option("--dir", "directory", default=None, metavar="PATH",
              help=f"Directory to list. Default: {DEFAULT_SCREENSHOT_DIR}")
@click.option("--open", "open_dir", is_flag=True, default=False,
              help="Open the screenshots folder in your file manager.")
def screenshots_cmd(directory: str | None, open_dir: bool) -> None:
    """List captured screenshots or open the screenshots folder.

    \b
    Examples:
      bdr screenshots                     # list from default folder
      bdr screenshots --dir ./shots       # list from a custom folder
      bdr screenshots --open              # open the folder in Finder / Explorer
    """
    target = pathlib.Path(directory).resolve() if directory else DEFAULT_SCREENSHOT_DIR

    if open_dir:
        if not target.exists():
            raise click.ClickException(f"Directory does not exist: {target}")
        if sys.platform == "darwin":
            subprocess.run(["open", str(target)], check=False)
        elif sys.platform == "win32":
            subprocess.run(["explorer", str(target)], check=False)
        else:
            subprocess.run(["xdg-open", str(target)], check=False)
        return

    if not target.exists() or not any(target.rglob("*.png")):
        click.echo(f"  No screenshots yet in {target}")
        click.echo(f"  Run a script with screenshot() calls to capture some.")
        return

    files = sorted(target.rglob("*.png"), key=lambda f: f.stat().st_mtime, reverse=True)
    click.echo(f"  {target}\n")
    for f in files:
        stat = f.stat()
        size_kb = stat.st_size / 1024
        mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
        rel = f.relative_to(target)
        click.echo(f"  {mtime}  {size_kb:6.1f} KB  {rel}")


# ---------------------------------------------------------------------------
# kill
# ---------------------------------------------------------------------------

@main.command()
@click.option("--status-file", default=None, metavar="PATH",
              help=f"Status file to read. Default: {DEFAULT_STATUS_FILE}")
@click.option("--force", is_flag=True, default=False,
              help="Send SIGKILL instead of SIGTERM.")
def kill(status_file: str | None, force: bool) -> None:
    """Kill the currently running bdr test.

    Reads the live status file to find the process ID and terminates it.
    The status file is removed after a successful kill.

    \b
    Examples:
      bdr kill
      bdr kill --force
      bdr kill --status-file ./my-run.json
    """
    import json
    import os
    import signal as _signal

    sf = pathlib.Path(status_file).resolve() if status_file else DEFAULT_STATUS_FILE

    if not sf.exists():
        raise click.ClickException(
            f"No status file found at {sf}\n"
            "  Is a bdr test currently running?"
        )

    try:
        data = json.loads(sf.read_text(encoding="utf-8"))
    except Exception as exc:
        raise click.ClickException(f"Could not read status file: {exc}")

    pid = data.get("pid")
    script = data.get("script", "unknown")
    started = data.get("started", "unknown")
    action_count = len(data.get("actions", []))

    if not pid:
        raise click.ClickException("Status file does not contain a PID.")

    click.echo(f"  script:  {script}")
    click.echo(f"  started: {started}")
    click.echo(f"  actions: {action_count} completed")
    click.echo(f"  pid:     {pid}")

    sig = _signal.SIGKILL if (force and hasattr(_signal, "SIGKILL")) else _signal.SIGTERM

    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        click.echo(f"  Process {pid} is no longer running — removing stale status file.")
        sf.unlink(missing_ok=True)
        return
    except PermissionError:
        raise click.ClickException(f"Permission denied to kill process {pid}.")

    sig_name = "SIGKILL" if sig == getattr(_signal, "SIGKILL", None) else "SIGTERM"
    click.echo(f"  sent {sig_name} to process {pid}")

    # Remove the status file — the process may not get a chance to clean up.
    sf.unlink(missing_ok=True)
    click.echo("  status file removed")


# ---------------------------------------------------------------------------
# install-browsers (hidden alias for backwards compatibility)
# ---------------------------------------------------------------------------

@main.command("install-browsers", hidden=True)
def install_browsers() -> None:
    """Alias for 'setup'. Deprecated — use 'bdr setup' instead."""
    subprocess.run([sys.executable, "-m", "playwright", "install"], check=True)
