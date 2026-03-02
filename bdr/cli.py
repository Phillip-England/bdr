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
      bdr extract URL SELECTOR   Generate a .el selector file from a live page
      bdr setup                  Install Playwright browsers
      bdr screenshots            List captured screenshots
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
def run(script: str, browser: str, headless: bool, slow: float,
        timeout: int, screenshot_dir: str | None) -> None:
    """Execute a .bdr script."""
    sdir = pathlib.Path(screenshot_dir).resolve() if screenshot_dir else None
    try:
        run_script(
            script,
            browser=browser,
            headed=not headless,
            slow_mo=slow,
            timeout=timeout,
            screenshot_dir=sdir,
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
# {dest.name}
# Created with: bdr new {dest.name}

# How long to wait for elements before failing (milliseconds).
timeout = 15000

# Where to save screenshots — defaults to ~/.bdr/screenshots/
# screenshot_dir("./screenshots")

# Define variables.
# $url = "https://example.com"
# $user = "me@example.com"

load("https://example.com")

# Interact with elements using CSS selector chains:
# .selector.click()
# #id.fill("value")
# .selector[0].click()       # pick the first matching element
# assert_title("Expected title")
# screenshot("result.png")

log("Script complete")
"""
    dest.write_text(template, encoding="utf-8")
    click.echo(f"  created: {dest}")


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
# install-browsers (hidden alias for backwards compatibility)
# ---------------------------------------------------------------------------

@main.command("install-browsers", hidden=True)
def install_browsers() -> None:
    """Alias for 'setup'. Deprecated — use 'bdr setup' instead."""
    subprocess.run([sys.executable, "-m", "playwright", "install"], check=True)
