"""bdr interpreter — executes tokenized .bdr lines against a Playwright page."""

from __future__ import annotations

import pathlib
import re
import time
import urllib.parse
from typing import TYPE_CHECKING

# Matches env("VAR"), env('VAR'), or env(VAR) — the lexer strips inner quotes
# when env() appears inside another call's args, but keeps them for assignments.
_ENV_CALL = re.compile(r'^env\(["\']?([^"\'()]+)["\']?\)$')

from .lexer import Line, tokenize
from .mock import MockError, resolve_mock

if TYPE_CHECKING:
    from playwright.sync_api import Page

DEFAULT_TIMEOUT = 30_000  # milliseconds
DEFAULT_SCREENSHOT_DIR = pathlib.Path.home() / ".bdr" / "screenshots"

# Actions supported by the element chain syntax: SELECTOR[n].action(args)
_ELEMENT_ACTIONS = {
    # interaction
    'click', 'fill', 'type', 'select', 'check', 'uncheck', 'hover', 'focus',
    # scrolling
    'scroll_to',
    # waiting
    'wait', 'wait_visible',
    # assertions
    'assert_text', 'assert_text_equals',
    'assert_visible', 'assert_hidden',
    'assert_exists', 'assert_not_exists',
    'assert_enabled', 'assert_disabled',
    'assert_checked', 'assert_unchecked',
    'assert_value', 'assert_attribute', 'assert_class', 'assert_count',
}


class BdrError(Exception):
    pass


# ---------------------------------------------------------------------------
# Human-readable Playwright error messages
# ---------------------------------------------------------------------------

_NET_ERRORS: dict[str, tuple[str, str]] = {
    "ERR_CONNECTION_REFUSED":       ("Connection refused",          "The connection was refused"),
    "ERR_NAME_NOT_RESOLVED":        ("Hostname not found",          "The domain could not be resolved"),
    "ERR_INTERNET_DISCONNECTED":    ("No internet connection",      "Your machine appears to be offline"),
    "ERR_CONNECTION_TIMED_OUT":     ("Connection timed out",        "The server took too long to respond"),
    "ERR_TIMED_OUT":                ("Network timed out",           "The request timed out"),
    "ERR_SSL_PROTOCOL_ERROR":       ("SSL/TLS error",               "The SSL handshake failed"),
    "ERR_CERT_AUTHORITY_INVALID":   ("Untrusted SSL certificate",   "The SSL certificate is not trusted by this machine"),
    "ERR_CERT_COMMON_NAME_INVALID": ("SSL certificate mismatch",    "The SSL certificate does not match the hostname"),
    "ERR_ADDRESS_UNREACHABLE":      ("Address unreachable",         "The server address is not reachable from this machine"),
}


def _humanize_playwright_error(command: str, exc: Exception) -> str:
    """Convert a raw Playwright exception into a short, user-friendly description."""
    raw = str(exc)

    # ── Network / navigation errors ─────────────────────────────────────────
    for code, (label, detail) in _NET_ERRORS.items():
        if code in raw:
            url_m = re.search(r'https?://[^\s]+', raw)
            if url_m:
                url = url_m.group(0).rstrip('/')
                parsed = urllib.parse.urlparse(url)
                host = parsed.hostname or ""
                port = parsed.port
                if host in ("localhost", "127.0.0.1", "::1"):
                    hint = f"Is a local server running on port {port}?" if port else "Is a local server running?"
                elif code == "ERR_NAME_NOT_RESOLVED":
                    hint = f"Check the spelling of '{host}' and your network connection."
                else:
                    hint = f"{detail}. Is '{host}' reachable from this machine?"
                return f"{label}: {url}\n  Hint: {hint}"
            return f"{label}\n  Hint: {detail}."

    exc_type = type(exc).__name__

    # ── Playwright TimeoutError (element/selector never appeared) ───────────
    if "TimeoutError" in exc_type or ("ms exceeded" in raw and "Timeout" in raw):
        timeout_m = re.search(r'(\d+)\s*ms', raw)
        timeout_s = f"{int(timeout_m.group(1)) / 1000:g}s" if timeout_m else "the configured timeout"
        for pat in (
            r"waiting for locator\('([^']+)'\)",
            r'waiting for locator\("([^"]+)"\)',
            r"waiting for selector '([^']+)'",
            r'waiting for selector "([^"]+)"',
        ):
            sel_m = re.search(pat, raw)
            if sel_m:
                selector = sel_m.group(1)
                doubled = int(timeout_m.group(1)) * 2 if timeout_m else 60000
                return (
                    f"Timed out after {timeout_s} — '{selector}' never appeared\n"
                    f"  Hint: Check the selector is correct and the element loads in time.\n"
                    f"  Hint: To allow more time add this near the top of your script:  timeout = {doubled}"
                )
        return (
            f"Timed out after {timeout_s}\n"
            f"  Hint: The page or element took too long to respond."
        )

    # ── Strict mode — selector matched more than one element ────────────────
    if "strict mode violation" in raw:
        sel_m = re.search(r'locator\("([^"]+)"\)', raw)
        count_m = re.search(r'resolved to (\d+) elements', raw)
        selector = sel_m.group(1) if sel_m else "the selector"
        count = count_m.group(1) if count_m else "multiple"
        return (
            f"Selector '{selector}' matched {count} elements — must match exactly one\n"
            f"  Hint: Add an index to pick a specific match, e.g. selector[0].action()"
        )

    # ── Element not visible ─────────────────────────────────────────────────
    if re.search(r'not visible|element is not visible', raw, re.IGNORECASE):
        return (
            f"Element is not visible on the page\n"
            f"  Hint: Use .scroll_to() to bring it into view, or .wait_visible() to wait for it."
        )

    # ── Element detached / removed from DOM ─────────────────────────────────
    if "detached" in raw:
        return (
            f"Element was removed from the page before the action could complete\n"
            f"  Hint: The page may have reloaded. Add .wait() before this command."
        )

    # ── Wrong element type for fill / type ──────────────────────────────────
    if re.search(r'not (an )?HTMLInput|not.*<input', raw, re.IGNORECASE):
        return (
            f"Cannot type into this element — it is not a text input\n"
            f"  Hint: The selector must point to an <input> or <textarea>."
        )

    # ── Browser executable missing ──────────────────────────────────────────
    if "Executable doesn't exist" in raw or "playwright install" in raw:
        return (
            f"Browser executable not found\n"
            f"  Hint: Run 'bdr setup' to install the required browsers."
        )

    # ── Fallback: strip Playwright's internal 'Call log' / '===' sections ──
    for marker in ("\nCall log:", "\n==="):
        if marker in raw:
            raw = raw[:raw.index(marker)]
    first_line = raw.strip().splitlines()[0] if raw.strip() else str(exc)
    return first_line


class Interpreter:
    def __init__(
        self,
        page: "Page",
        slow_mo: float = 0.0,
        timeout: int = DEFAULT_TIMEOUT,
        base_dir: pathlib.Path | None = None,
        screenshot_dir: pathlib.Path | None = None,
        env_vars: dict[str, str] | None = None,
    ) -> None:
        self._page = page
        self._slow_mo = slow_mo
        self._timeout = timeout
        self._variables: dict[str, str] = {}
        self._env: dict[str, str] = env_vars or {}
        self._base_dir: pathlib.Path = (base_dir or pathlib.Path.cwd()).resolve()
        self._exec_stack: list[pathlib.Path] = []
        self._screenshot_dir: pathlib.Path = (
            screenshot_dir or DEFAULT_SCREENSHOT_DIR
        ).resolve()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, lines: list[Line]) -> None:
        for line in lines:
            self._dispatch(line)
            if self._slow_mo:
                time.sleep(self._slow_mo)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, line: Line) -> None:
        handlers = {
            # navigation
            "load":               self._load,
            "back":               self._back,
            "forward":            self._forward,
            "refresh":            self._refresh,
            # keyboard / scroll (page-level, not element-specific)
            "press":              self._press,
            "scroll_up":          self._scroll_up,
            "scroll_down":        self._scroll_down,
            # waiting (page/text level)
            "wait":               self._wait,
            "wait_for_text":      self._wait_for_text,
            "wait_until_loaded":  self._wait_until_loaded,
            # assertions — page level
            "assert_title":          self._assert_title,
            "assert_title_equals":   self._assert_title_equals,
            "assert_url":            self._assert_url,
            "assert_url_equals":     self._assert_url_equals,
            "assert_page_contains":  self._assert_page_contains,
            # composition
            "exec":           self._exec,
            # output
            "screenshot_dir": self._set_screenshot_dir,
            "screenshot":     self._screenshot,
            "log":            self._log,
            # element chain syntax (produced by the lexer)
            "__element__":    self._element,
            # assignment — manages its own resolution (key must not be resolved)
            "__assign__":     self._assign,
        }
        handler = handlers.get(line.command)
        if handler is None:
            raise BdrError(f"Line {line.number}: unknown command '{line.command}()'")

        if line.command == "__assign__":
            target = line
        else:
            try:
                resolved = [self._resolve(line.number, a) for a in line.args]
            except BdrError:
                raise
            target = Line(line.number, line.command, resolved, line.raw)

        try:
            handler(target)
        except BdrError:
            raise
        except Exception as exc:
            msg = _humanize_playwright_error(line.command, exc)
            raise BdrError(
                f"Line {line.number}: {msg}\n  Command: {line.raw}"
            ) from exc

    # ------------------------------------------------------------------
    # Variable resolution
    # ------------------------------------------------------------------

    def _resolve(self, lineno: int, value: str) -> str:
        # env("VAR") / env('VAR') / env(VAR) — look up in the loaded .env
        m = _ENV_CALL.match(value.strip())
        if m:
            var_name = m.group(1)
            if var_name not in self._env:
                raise BdrError(
                    f"Line {lineno}: env variable '{var_name}' is not set\n"
                    f"  Hint: Add {var_name}=... to the .env file in your script's directory."
                )
            return self._env[var_name]

        # random_*() — mock data generators
        try:
            generated = resolve_mock(value, lineno)
        except MockError as exc:
            raise BdrError(str(exc)) from exc
        if generated is not None:
            return generated

        if not value.startswith('$'):
            return value
        name = value[1:]
        if name not in self._variables:
            raise BdrError(f"Line {lineno}: undefined variable '{value}'")
        return self._variables[name]

    # ------------------------------------------------------------------
    # Assignment  ($name = value  /  timeout = ms)
    # ------------------------------------------------------------------

    def _assign(self, line: Line) -> None:
        self._require_args(line, 2)
        key = line.args[0]
        value = self._resolve(line.number, line.args[1])

        if key == 'timeout':
            try:
                self._timeout = int(float(value))
            except ValueError:
                raise BdrError(
                    f"Line {line.number}: timeout must be a number of milliseconds, got '{value}'"
                )
        elif key.startswith('$'):
            self._variables[key[1:]] = value
        else:
            raise BdrError(f"Line {line.number}: unknown setting '{key}'")

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _load(self, line: Line) -> None:
        """Navigate the browser to a URL.

        Automatically prepends http:// when no scheme is provided so that
        bare hosts like "localhost:3000" work without extra typing.
        """
        self._require_args(line, 1)
        url = line.args[0]
        if not url.startswith(('http://', 'https://')):
            url = 'http://' + url
        self._page.goto(url)

    def _back(self, line: Line) -> None:
        self._page.go_back()

    def _forward(self, line: Line) -> None:
        self._page.go_forward()

    def _refresh(self, line: Line) -> None:
        self._page.reload()

    # ------------------------------------------------------------------
    # Element chain handler
    # ------------------------------------------------------------------

    def _element(self, line: Line) -> None:
        """Execute an element chain: SELECTOR[n].action(args)."""
        if len(line.args) < 3:
            raise BdrError(f"Line {line.number}: malformed element chain")

        selector = line.args[0]
        index = int(line.args[1])
        action = line.args[2]
        action_args = line.args[3:]

        if action not in _ELEMENT_ACTIONS:
            raise BdrError(
                f"Line {line.number}: unknown element action '.{action}()'\n"
                f"  Available actions: {', '.join(sorted(_ELEMENT_ACTIONS))}"
            )

        loc = self._page.locator(selector).nth(index) if index >= 0 else self._page.locator(selector)

        if action == 'click':
            loc.click(timeout=self._timeout)

        elif action == 'fill':
            if not action_args:
                raise BdrError(f"Line {line.number}: .fill() requires a value argument")
            loc.fill(action_args[0], timeout=self._timeout)

        elif action == 'type':
            if not action_args:
                raise BdrError(f"Line {line.number}: .type() requires a value argument")
            loc.wait_for(timeout=self._timeout)
            loc.type(action_args[0])

        elif action == 'select':
            if not action_args:
                raise BdrError(f"Line {line.number}: .select() requires an option value")
            loc.select_option(action_args[0], timeout=self._timeout)

        elif action == 'check':
            loc.check(timeout=self._timeout)

        elif action == 'uncheck':
            loc.uncheck(timeout=self._timeout)

        elif action == 'hover':
            loc.hover(timeout=self._timeout)

        elif action == 'focus':
            loc.focus(timeout=self._timeout)

        elif action == 'scroll_to':
            loc.scroll_into_view_if_needed(timeout=self._timeout)

        elif action == 'wait':
            loc.wait_for(timeout=self._timeout)

        elif action == 'wait_visible':
            loc.wait_for(state='visible', timeout=self._timeout)

        elif action == 'assert_text':
            if not action_args:
                raise BdrError(f"Line {line.number}: .assert_text() requires expected text")
            loc.wait_for(timeout=self._timeout)
            actual = loc.inner_text()
            if action_args[0] not in actual:
                raise BdrError(
                    f"Line {line.number}: assert_text failed for '{selector}'"
                    f" — expected '{action_args[0]}', got '{actual}'"
                )

        elif action == 'assert_text_equals':
            if not action_args:
                raise BdrError(f"Line {line.number}: .assert_text_equals() requires expected text")
            loc.wait_for(timeout=self._timeout)
            actual = loc.inner_text().strip()
            if actual != action_args[0]:
                raise BdrError(
                    f"Line {line.number}: assert_text_equals failed for '{selector}'"
                    f" — expected '{action_args[0]}', got '{actual}'"
                )

        elif action == 'assert_visible':
            loc.wait_for(state='visible', timeout=self._timeout)

        elif action == 'assert_hidden':
            if loc.is_visible():
                raise BdrError(
                    f"Line {line.number}: assert_hidden failed — '{selector}' is visible"
                )

        elif action == 'assert_exists':
            loc.wait_for(state='attached', timeout=self._timeout)

        elif action == 'assert_not_exists':
            total = self._page.locator(selector).count()
            exists = (index < total) if index >= 0 else (total > 0)
            if exists:
                raise BdrError(
                    f"Line {line.number}: assert_not_exists failed"
                    f" — '{selector}' found in DOM"
                )

        elif action == 'assert_enabled':
            loc.wait_for(timeout=self._timeout)
            if not loc.is_enabled():
                raise BdrError(
                    f"Line {line.number}: assert_enabled failed — '{selector}' is disabled"
                )

        elif action == 'assert_disabled':
            loc.wait_for(timeout=self._timeout)
            if loc.is_enabled():
                raise BdrError(
                    f"Line {line.number}: assert_disabled failed — '{selector}' is enabled"
                )

        elif action == 'assert_checked':
            loc.wait_for(timeout=self._timeout)
            if not loc.is_checked():
                raise BdrError(
                    f"Line {line.number}: assert_checked failed — '{selector}' is not checked"
                )

        elif action == 'assert_unchecked':
            loc.wait_for(timeout=self._timeout)
            if loc.is_checked():
                raise BdrError(
                    f"Line {line.number}: assert_unchecked failed — '{selector}' is checked"
                )

        elif action == 'assert_value':
            if not action_args:
                raise BdrError(f"Line {line.number}: .assert_value() requires an expected value")
            loc.wait_for(timeout=self._timeout)
            actual = loc.input_value()
            if actual != action_args[0]:
                raise BdrError(
                    f"Line {line.number}: assert_value failed for '{selector}'"
                    f" — expected '{action_args[0]}', got '{actual}'"
                )

        elif action == 'assert_attribute':
            if len(action_args) < 2:
                raise BdrError(
                    f"Line {line.number}: .assert_attribute() requires an attribute name and expected value"
                )
            loc.wait_for(timeout=self._timeout)
            actual = loc.get_attribute(action_args[0])
            if actual is None or action_args[1] not in actual:
                raise BdrError(
                    f"Line {line.number}: assert_attribute failed for '{selector}[{action_args[0]}]'"
                    f" — expected '{action_args[1]}', got '{actual}'"
                )

        elif action == 'assert_class':
            if not action_args:
                raise BdrError(f"Line {line.number}: .assert_class() requires a class name")
            loc.wait_for(timeout=self._timeout)
            classes = (loc.get_attribute('class') or '').split()
            if action_args[0] not in classes:
                raise BdrError(
                    f"Line {line.number}: assert_class failed for '{selector}'"
                    f" — expected class '{action_args[0]}', has '{' '.join(classes)}'"
                )

        elif action == 'assert_count':
            if not action_args:
                raise BdrError(f"Line {line.number}: .assert_count() requires a number")
            try:
                expected = int(action_args[0])
            except ValueError:
                raise BdrError(
                    f"Line {line.number}: .assert_count() expects an integer, got '{action_args[0]}'"
                )
            actual = self._page.locator(selector).count()
            if actual != expected:
                raise BdrError(
                    f"Line {line.number}: assert_count failed for '{selector}'"
                    f" — expected {expected}, got {actual}"
                )

    # ------------------------------------------------------------------
    # Keyboard / page-level interaction
    # ------------------------------------------------------------------

    def _press(self, line: Line) -> None:
        self._require_args(line, 1)
        self._page.keyboard.press(line.args[0])

    def _scroll_up(self, line: Line) -> None:
        self._page.mouse.wheel(0, -500)

    def _scroll_down(self, line: Line) -> None:
        self._page.mouse.wheel(0, 500)

    # ------------------------------------------------------------------
    # Waiting (page / text level)
    # ------------------------------------------------------------------

    def _wait(self, line: Line) -> None:
        self._require_args(line, 1)
        try:
            seconds = float(line.args[0])
        except ValueError:
            raise BdrError(
                f"Line {line.number}: wait() expects seconds as a number, got '{line.args[0]}'"
            )
        time.sleep(seconds)

    def _wait_for_text(self, line: Line) -> None:
        self._require_args(line, 1)
        self._page.wait_for_selector(f"text={line.args[0]}", timeout=self._timeout)

    def _wait_until_loaded(self, line: Line) -> None:
        """Block until the page URL contains *path* and the page is fully loaded."""
        self._require_args(line, 1)
        path = line.args[0]
        if path.startswith(("http://", "https://")):
            pattern = path
        else:
            pattern = f"**{path}**"
        self._page.wait_for_url(pattern, wait_until="load", timeout=self._timeout)

    # ------------------------------------------------------------------
    # Assertions — page level
    # ------------------------------------------------------------------

    def _assert_title(self, line: Line) -> None:
        self._require_args(line, 1)
        actual = self._page.title()
        if line.args[0] not in actual:
            raise BdrError(
                f"Line {line.number}: assert_title failed — expected '{line.args[0]}', got '{actual}'"
            )

    def _assert_title_equals(self, line: Line) -> None:
        self._require_args(line, 1)
        actual = self._page.title()
        if actual != line.args[0]:
            raise BdrError(
                f"Line {line.number}: assert_title_equals failed"
                f" — expected '{line.args[0]}', got '{actual}'"
            )

    def _assert_url(self, line: Line) -> None:
        self._require_args(line, 1)
        actual = self._page.url
        if line.args[0] not in actual:
            raise BdrError(
                f"Line {line.number}: assert_url failed — expected '{line.args[0]}', got '{actual}'"
            )

    def _assert_url_equals(self, line: Line) -> None:
        self._require_args(line, 1)
        actual = self._page.url
        if actual != line.args[0]:
            raise BdrError(
                f"Line {line.number}: assert_url_equals failed"
                f" — expected '{line.args[0]}', got '{actual}'"
            )

    def _assert_page_contains(self, line: Line) -> None:
        self._require_args(line, 1)
        text = line.args[0]
        content = self._page.locator("body").inner_text()
        if text not in content:
            raise BdrError(
                f"Line {line.number}: assert_page_contains failed"
                f" — '{text}' not found anywhere on the page"
            )

    # ------------------------------------------------------------------
    # Script composition
    # ------------------------------------------------------------------

    def _exec(self, line: Line) -> None:
        self._require_args(line, 1)
        target = (self._base_dir / line.args[0]).resolve()

        if not target.exists():
            raise BdrError(f"Line {line.number}: exec — file not found: {target}")

        if target in self._exec_stack:
            chain = " -> ".join(p.name for p in self._exec_stack)
            raise BdrError(
                f"Line {line.number}: exec — circular import: {chain} -> {target.name}"
            )

        source = target.read_text(encoding="utf-8")
        try:
            child_lines = tokenize(source)
        except SyntaxError as exc:
            raise BdrError(
                f"Line {line.number}: exec — syntax error in {target.name}: {exc}"
            ) from exc

        print(f"  exec: {target.name}  ({len(child_lines)} commands)")

        saved_base_dir = self._base_dir
        self._base_dir = target.parent
        self._exec_stack.append(target)
        try:
            self.run(child_lines)
        finally:
            self._exec_stack.pop()
            self._base_dir = saved_base_dir

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def _set_screenshot_dir(self, line: Line) -> None:
        self._require_args(line, 1)
        path = pathlib.Path(line.args[0])
        if not path.is_absolute():
            path = pathlib.Path.cwd() / path
        self._screenshot_dir = path.resolve()

    def _screenshot(self, line: Line) -> None:
        self._require_args(line, 1)
        dest = pathlib.Path(line.args[0])
        if not dest.is_absolute():
            dest = self._screenshot_dir / dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._page.screenshot(path=str(dest))
        print(f"  screenshot → {dest}")

    def _log(self, line: Line) -> None:
        print(f"  log: {' '.join(line.args)}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_args(self, line: Line, n: int) -> None:
        if len(line.args) < n:
            raise BdrError(
                f"Line {line.number}: {line.command}() requires at least {n} argument(s),"
                f" got {len(line.args)}"
            )
