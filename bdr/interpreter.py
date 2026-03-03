"""bdr interpreter — executes tokenized .bdr lines against a Playwright page."""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys
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
    'click', 'fill', 'type',
    'select',        # select by visible label text  (what the user reads)
    'select_value',  # select by option value attr   (the HTML value="...")
    'select_index',  # select by 0-based position    (first option = 0)
    'check', 'uncheck', 'hover', 'focus',
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

    # ── Dropdown option not found ───────────────────────────────────────────
    if re.search(r'did not find option|no option', raw, re.IGNORECASE):
        opt_m = re.search(r"(?:label|value)[=\s]+['\"]?([^'\"]+)['\"]?", raw, re.IGNORECASE)
        opt = f"'{opt_m.group(1)}'" if opt_m else "the requested option"
        return (
            f"Dropdown option not found: {opt}\n"
            f"  Hint: .select() matches visible label text — use the exact text shown in the dropdown.\n"
            f"  Hint: .select_value() matches the HTML value= attribute instead.\n"
            f"  Hint: .select_index(n) picks by position (0 = first option) if the text/value is unknown."
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
        self._functions: dict[str, tuple[list[str], list]] = {}
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
        # First pass: register all function definitions (enables forward references).
        for line in lines:
            if line.command == '__func_def__':
                self._register_function(line)
        # Second pass: execute (function defs are skipped — already registered).
        for line in lines:
            if line.command == '__func_def__':
                continue
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
            "load_clipboard":     self._load_clipboard,
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
            # semantic locator chain: text(...).action() / role(...).action() / etc.
            "__locator__":    self._locator,
            # assignment — manages its own resolution (key must not be resolved)
            "__assign__":     self._assign,
        }
        handler = handlers.get(line.command)
        if handler is None:
            if line.command in self._functions:
                # User-defined function call — resolve args then invoke.
                try:
                    resolved = [self._resolve(line.number, a) for a in line.args]
                except BdrError:
                    raise
                call_line = Line(line.number, line.command, resolved, line.raw)
                try:
                    self._call_function(call_line)
                except BdrError:
                    raise
                except Exception as exc:
                    msg = _humanize_playwright_error(line.command, exc)
                    raise BdrError(
                        f"Line {line.number}: {msg}\n  Command: {line.raw}"
                    ) from exc
                return
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
        elif key == 'slow':
            try:
                self._slow_mo = float(value)
            except ValueError:
                raise BdrError(
                    f"Line {line.number}: slow must be a number of seconds, got '{value}'"
                )
        elif key.startswith('$'):
            self._variables[key[1:]] = value
        else:
            raise BdrError(f"Line {line.number}: unknown setting '{key}'")

    # ------------------------------------------------------------------
    # User-defined functions
    # ------------------------------------------------------------------

    def _register_function(self, line: Line) -> None:
        """Store a function definition for later invocation."""
        func_name = line.args[0]
        params = line.args[1:]
        self._functions[func_name] = (params, line.body or [])

    def _call_function(self, line: Line) -> None:
        """Execute a user-defined function with already-resolved arguments."""
        func_name = line.command
        params, body = self._functions[func_name]
        call_args = line.args

        if len(call_args) != len(params):
            raise BdrError(
                f"Line {line.number}: function '{func_name}' expects {len(params)} argument(s),"
                f" got {len(call_args)}"
            )

        # Save variable state; bind parameters as local variables.
        saved_vars = dict(self._variables)
        for param, arg in zip(params, call_args):
            self._variables[param[1:]] = arg  # '$name' -> 'name'

        try:
            self.run(body)
        finally:
            # Restore variables — changes made inside the function are local.
            self._variables = saved_vars

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _load(self, line: Line) -> None:
        """Navigate the browser to a URL.

        Automatically prepends http:// when no scheme is provided so that
        bare hosts like "localhost:3000" work without extra typing.
        """
        self._require_args(line, 1)
        url = self._normalize_url(line.args[0])
        try:
            self._page.goto(url)
        except Exception as exc:
            msg = _humanize_playwright_error('load', exc)
            raise BdrError(
                f"Line {line.number}: {msg}\n"
                f"  URL attempted: {url}"
            ) from exc

    def _load_clipboard(self, line: Line) -> None:
        if line.args:
            raise BdrError(
                f"Line {line.number}: load_clipboard() does not take arguments,"
                f" got {len(line.args)}"
            )

        raw_url = self._read_clipboard_text(line.number)
        url = self._normalize_url(raw_url)
        try:
            self._page.goto(url)
        except Exception as exc:
            msg = _humanize_playwright_error('load_clipboard', exc)
            raise BdrError(
                f"Line {line.number}: {msg}\n"
                f"  URL attempted from clipboard: {url}"
            ) from exc

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

        try:
            self._run_element_action(line, loc, selector, index, action, action_args)
        except BdrError:
            raise  # already formatted — pass through untouched
        except Exception as exc:
            raw = str(exc)
            exc_type = type(exc).__name__
            if "TimeoutError" in exc_type or ("ms exceeded" in raw and "Timeout" in raw):
                raise self._element_timeout_error(line, selector, index, action) from exc
            # Non-timeout Playwright error — use the general humanizer.
            msg = _humanize_playwright_error(line.command, exc)
            raise BdrError(
                f"Line {line.number}: {msg}\n  Command: {line.raw}"
            ) from exc

    def _run_element_action(
        self,
        line: Line,
        loc: "any",
        selector: str,
        index: int,
        action: str,
        action_args: list[str],
    ) -> None:
        """Dispatch the individual element action. Called from _element()."""

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
            # Select by visible label — the text the user reads in the dropdown.
            if not action_args:
                raise BdrError(f"Line {line.number}: .select() requires the visible option text")
            try:
                loc.select_option(label=action_args[0], timeout=self._timeout)
            except Exception as exc:
                if "did not find option" in str(exc).lower() or "no option" in str(exc).lower():
                    raise BdrError(
                        f"Line {line.number}: .select() could not find an option with label '{action_args[0]}'\n"
                        f"  Hint: Use the exact visible text from the dropdown.\n"
                        f"  Hint: If the option is identified by its value= attribute, use .select_value() instead."
                    ) from exc
                raise

        elif action == 'select_value':
            # Select by the option's value= attribute (the HTML value, not the visible text).
            if not action_args:
                raise BdrError(f"Line {line.number}: .select_value() requires an option value attribute")
            try:
                loc.select_option(value=action_args[0], timeout=self._timeout)
            except Exception as exc:
                if "did not find option" in str(exc).lower() or "no option" in str(exc).lower():
                    raise BdrError(
                        f"Line {line.number}: .select_value() could not find an option with value='{action_args[0]}'\n"
                        f"  Hint: Check the HTML — the value= attribute may differ from the visible text.\n"
                        f"  Hint: To select by visible text instead, use .select()."
                    ) from exc
                raise

        elif action == 'select_index':
            # Select by 0-based position — first option is 0.
            if not action_args:
                raise BdrError(f"Line {line.number}: .select_index() requires a position number")
            try:
                pos = int(action_args[0])
            except ValueError:
                raise BdrError(
                    f"Line {line.number}: .select_index() expects an integer position, got '{action_args[0]}'"
                )
            try:
                loc.select_option(index=pos, timeout=self._timeout)
            except Exception as exc:
                if "did not find option" in str(exc).lower() or "no option" in str(exc).lower():
                    raise BdrError(
                        f"Line {line.number}: .select_index({pos}) — no option at position {pos}\n"
                        f"  Hint: Positions are 0-based. If the dropdown has 3 options, valid positions are 0, 1, 2."
                    ) from exc
                raise

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

    def _locator(self, line: Line) -> None:
        """Execute a semantic locator chain: text(...).action() / role(...).action() / etc.

        Args layout (produced by the lexer):
            [locator_type, n_locator_args, *locator_args, index, action, *action_args]
        """
        if len(line.args) < 4:
            raise BdrError(f"Line {line.number}: malformed locator chain")

        locator_type = line.args[0]
        try:
            n = int(line.args[1])
        except (ValueError, IndexError):
            raise BdrError(f"Line {line.number}: malformed locator chain (bad arg count)")

        if len(line.args) < 2 + n + 2:
            raise BdrError(f"Line {line.number}: malformed locator chain (too few args)")

        locator_args = line.args[2: 2 + n]
        index = int(line.args[2 + n])
        action = line.args[2 + n + 1]
        action_args = line.args[2 + n + 2:]

        if action not in _ELEMENT_ACTIONS:
            raise BdrError(
                f"Line {line.number}: unknown element action '.{action}()'\n"
                f"  Available actions: {', '.join(sorted(_ELEMENT_ACTIONS))}"
            )

        # Build the Playwright locator from the semantic type.
        if locator_type == 'text':
            if not locator_args:
                raise BdrError(f"Line {line.number}: text() requires a text content argument")
            exact = len(locator_args) > 1 and locator_args[1].lower() in ('exact', 'true')
            loc = self._page.get_by_text(locator_args[0], exact=exact)

        elif locator_type == 'role':
            if not locator_args:
                raise BdrError(f"Line {line.number}: role() requires an ARIA role argument")
            role_name = locator_args[0]
            name = locator_args[1] if len(locator_args) > 1 else None
            loc = self._page.get_by_role(role_name, name=name) if name else self._page.get_by_role(role_name)

        elif locator_type == 'label':
            if not locator_args:
                raise BdrError(f"Line {line.number}: label() requires a label text argument")
            exact = len(locator_args) > 1 and locator_args[1].lower() in ('exact', 'true')
            loc = self._page.get_by_label(locator_args[0], exact=exact)

        elif locator_type == 'placeholder':
            if not locator_args:
                raise BdrError(f"Line {line.number}: placeholder() requires a placeholder text argument")
            exact = len(locator_args) > 1 and locator_args[1].lower() in ('exact', 'true')
            loc = self._page.get_by_placeholder(locator_args[0], exact=exact)

        elif locator_type == 'testid':
            if not locator_args:
                raise BdrError(f"Line {line.number}: testid() requires a test ID argument")
            loc = self._page.get_by_test_id(locator_args[0])

        elif locator_type == 'alt':
            if not locator_args:
                raise BdrError(f"Line {line.number}: alt() requires an alt-text argument")
            exact = len(locator_args) > 1 and locator_args[1].lower() in ('exact', 'true')
            loc = self._page.get_by_alt_text(locator_args[0], exact=exact)

        elif locator_type == 'title':
            if not locator_args:
                raise BdrError(f"Line {line.number}: title() requires a title attribute argument")
            exact = len(locator_args) > 1 and locator_args[1].lower() in ('exact', 'true')
            loc = self._page.get_by_title(locator_args[0], exact=exact)

        elif locator_type == 'xpath':
            if not locator_args:
                raise BdrError(f"Line {line.number}: xpath() requires an XPath expression")
            loc = self._page.locator(f"xpath={locator_args[0]}")

        else:
            raise BdrError(f"Line {line.number}: unknown locator type '{locator_type}'")

        if index >= 0:
            loc = loc.nth(index)

        selector_display = f"{locator_type}({', '.join(repr(a) for a in locator_args)})"
        try:
            self._run_element_action(line, loc, selector_display, index, action, action_args)
        except BdrError:
            raise
        except Exception as exc:
            raw = str(exc)
            exc_type = type(exc).__name__
            if "TimeoutError" in exc_type or ("ms exceeded" in raw and "Timeout" in raw):
                raise self._element_timeout_error(line, selector_display, index, action) from exc
            msg = _humanize_playwright_error(line.command, exc)
            raise BdrError(
                f"Line {line.number}: {msg}\n  Command: {line.raw}"
            ) from exc

    def _element_timeout_error(
        self,
        line: Line,
        selector: str,
        index: int,
        action: str,
    ) -> BdrError:
        """Build a rich BdrError for an element action that timed out.

        Inspects the live page to report exactly what was found (or not found),
        which page the browser was on, and what to try next.
        """
        timeout_s = f"{self._timeout / 1000:g}s"
        index_str = f"[{index}]" if index >= 0 else ""

        # Inspect the live page — these calls are synchronous and instant.
        try:
            count = self._page.locator(selector).count()
        except Exception:
            count = -1
        try:
            url   = self._page.url
            title = self._page.title()
        except Exception:
            url, title = "unknown", ""

        parts: list[str] = [
            f"Line {line.number}: Timed out after {timeout_s}"
            f" — '{selector}{index_str}.{action}()' did not complete",
            f"  Command: {line.raw}",
        ]

        # --- What was on the page? -------------------------------------------
        if count == 0:
            parts.append(
                f"  Selector '{selector}' matched 0 elements — nothing was found."
            )
            parts.append(f"  Hint: Check the selector for typos (class names are case-sensitive).")
            parts.append(f"  Hint: Open DevTools on the page and run: document.querySelectorAll('{selector}')")
        elif index >= 0 and index >= count:
            parts.append(
                f"  Selector '{selector}' matched {count} element(s),"
                f" but index [{index}] is out of range — valid indices are 0 to {count - 1}."
            )
            parts.append(f"  Hint: Change the index or remove it to target all {count} match(es).")
        elif count > 0:
            parts.append(
                f"  Selector '{selector}' matched {count} element(s),"
                f" but .{action}() could not complete within {timeout_s}."
            )
            if action in ('click', 'fill', 'type', 'select', 'select_value', 'select_index'):
                parts.append(
                    f"  Hint: The element may be hidden, disabled, or covered by another element."
                )
                parts.append(f"  Hint: Try .scroll_to() before this line to bring it into view.")
            elif action in ('assert_visible', 'wait_visible'):
                parts.append(f"  Hint: The element exists but is not visible. Check for CSS display:none or visibility:hidden.")
        else:
            parts.append(f"  Could not inspect the page after the timeout.")

        # --- Where was the browser? ------------------------------------------
        if url and url != "unknown":
            parts.append(f"  Page URL:   {url}")
        if title:
            parts.append(f"  Page title: {title}")

        # --- Universal hints -------------------------------------------------
        parts.append(
            f"  Hint: To wait longer, increase the timeout: timeout = {self._timeout * 2}"
        )

        return BdrError("\n".join(parts))

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

    def _normalize_url(self, url: str) -> str:
        cleaned = url.strip()
        if not cleaned.startswith(('http://', 'https://')):
            return 'http://' + cleaned
        return cleaned

    def _read_clipboard_text(self, lineno: int) -> str:
        """Read plain text from the system clipboard."""
        commands: list[list[str]]
        if sys.platform == "darwin":
            commands = [["pbpaste"]]
        elif sys.platform == "win32":
            commands = [
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
                ["pwsh", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
            ]
        else:
            commands = [
                ["wl-paste", "--no-newline"],
                ["xclip", "-selection", "clipboard", "-o"],
                ["xsel", "--clipboard", "--output"],
            ]

        available = [cmd for cmd in commands if shutil.which(cmd[0])]
        if not available:
            raise BdrError(
                f"Line {lineno}: could not read clipboard on this machine\n"
                f"  Hint: Install a clipboard utility"
                f" ({' / '.join(cmd[0] for cmd in commands)})."
            )

        for cmd in available:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                continue
            value = result.stdout.strip()
            if not value:
                raise BdrError(
                    f"Line {lineno}: clipboard is empty\n"
                    f"  Hint: Copy a URL first, then call load_clipboard()."
                )
            return value

        raise BdrError(
            f"Line {lineno}: failed to read clipboard contents"
        )

    def _require_args(self, line: Line, n: int) -> None:
        if len(line.args) < n:
            raise BdrError(
                f"Line {line.number}: {line.command}() requires at least {n} argument(s),"
                f" got {len(line.args)}"
            )
