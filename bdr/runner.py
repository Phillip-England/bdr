"""bdr runner — loads a .bdr file and executes it."""

from __future__ import annotations

import pathlib

from playwright.sync_api import sync_playwright

from .interpreter import DEFAULT_SCREENSHOT_DIR, Interpreter, _ELEMENT_ACTIONS
from .lexer import tokenize


def _load_dotenv(script_dir: pathlib.Path) -> dict[str, str]:
    """Parse a .env file in *script_dir* and return a {KEY: value} mapping.

    Handles blank lines, ``# comments``, and values wrapped in single or double
    quotes.  Returns an empty dict when no .env file is present.
    """
    env_file = script_dir / ".env"
    if not env_file.exists():
        return {}
    env: dict[str, str] = {}
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip surrounding quotes from the value.
        if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
            value = value[1:-1]
        if key:
            env[key] = value
    return env


# Commands and their minimum required argument counts — kept in sync with Interpreter.
_KNOWN_COMMANDS: dict[str, int] = {
    # navigation
    "load": 1, "back": 0, "forward": 0, "refresh": 0,
    # keyboard / page-level interaction
    "press": 1, "scroll_up": 0, "scroll_down": 0,
    # waiting (page / text level)
    "wait": 1, "wait_for_text": 1, "wait_until_loaded": 1,
    # assertions — page level
    "assert_title": 1, "assert_title_equals": 1,
    "assert_url": 1, "assert_url_equals": 1,
    "assert_page_contains": 1,
    # composition + output
    "exec": 1, "screenshot_dir": 1, "screenshot": 1, "log": 0,
    # element chain syntax (produced by the lexer for SELECTOR[n].action(args))
    # args: [selector, index, action, *action_args] — minimum 3
    "__element__": 3,
    # assignment (produced by the lexer for $var = ... and timeout = ...)
    "__assign__": 2,
}


def check_script(
    path: str | pathlib.Path,
    _visited: set[pathlib.Path] | None = None,
) -> list[str]:
    """Parse and validate a script (and any exec'd sub-scripts) without a browser.

    Returns a (possibly empty) list of human-readable error strings.
    Follows exec references recursively and detects circular imports.
    """
    script_path = pathlib.Path(path).resolve()

    if _visited is None:
        _visited = set()

    if script_path in _visited:
        return [f"Circular exec: {script_path.name}"]
    _visited.add(script_path)

    if not script_path.exists():
        return [f"Script not found: {script_path}"]

    source = script_path.read_text(encoding="utf-8")
    try:
        lines = tokenize(source)
    except SyntaxError as exc:
        return [str(exc)]

    errors: list[str] = []
    for line in lines:
        if line.command not in _KNOWN_COMMANDS:
            errors.append(f"Line {line.number}: unknown command '{line.command}'")
            continue

        required = _KNOWN_COMMANDS[line.command]
        if len(line.args) < required:
            errors.append(
                f"Line {line.number}: '{line.command}' requires at least {required}"
                f" argument(s), got {len(line.args)}"
            )
            continue

        # Validate element chain action names.
        if line.command == "__element__" and len(line.args) >= 3:
            action = line.args[2]
            if action not in _ELEMENT_ACTIONS:
                errors.append(
                    f"Line {line.number}: unknown element action '.{action}()'"
                )
                continue

        # Recursively validate exec'd scripts.
        if line.command == "exec":
            child_path = (script_path.parent / line.args[0]).resolve()
            child_errors = check_script(child_path, _visited)
            errors.extend(f"[{child_path.name}] {e}" for e in child_errors)

    return errors


def run_script(
    path: str | pathlib.Path,
    browser: str = "chromium",
    headed: bool = True,
    slow_mo: float = 0.0,
    timeout: int = 30_000,
    screenshot_dir: pathlib.Path | None = None,
) -> None:
    script_path = pathlib.Path(path)
    if not script_path.exists():
        raise FileNotFoundError(f"Script not found: {script_path}")

    source = script_path.read_text(encoding="utf-8")
    try:
        lines = tokenize(source)
    except SyntaxError as exc:
        from .interpreter import BdrError
        raise BdrError(str(exc)) from exc

    effective_screenshot_dir = screenshot_dir or DEFAULT_SCREENSHOT_DIR
    env_vars = _load_dotenv(script_path.parent)

    print(f"bdr running: {script_path.name}  ({len(lines)} commands)")
    print(f"  screenshots → {effective_screenshot_dir}")
    if env_vars:
        print(f"  .env → {len(env_vars)} variable(s) loaded")

    with sync_playwright() as pw:
        browser_type = getattr(pw, browser)
        try:
            b = browser_type.launch(headless=not headed)
        except Exception as exc:
            from .interpreter import BdrError
            exc_msg = str(exc)
            if "Executable doesn't exist" in exc_msg or "playwright install" in exc_msg.lower():
                raise BdrError(
                    f"Browser '{browser}' is not installed\n"
                    f"  Hint: Run 'bdr setup' to install it."
                ) from exc
            raise BdrError(f"Failed to launch browser '{browser}': {exc_msg}") from exc
        page = b.new_page()
        try:
            interpreter = Interpreter(
                page,
                slow_mo=slow_mo,
                timeout=timeout,
                base_dir=script_path.parent,
                screenshot_dir=effective_screenshot_dir,
                env_vars=env_vars,
            )
            interpreter.run(lines)
        finally:
            b.close()

    print("Done.")
