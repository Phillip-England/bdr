"""Tokenizer for .bdr scripts.

Comments
--------
Three comment styles are supported:

  // line comment          -- from // to end of line
  /* block comment */      -- can span multiple lines
  # legacy line comment    -- original style; still accepted

All comment styles are stripped before parsing, so they may appear
anywhere — on their own line or at the end of a statement line.

  // navigate to the app
  load("localhost:3000")       // barehost: http:// is added automatically

  /* fill credentials
     from environment */
  #email.fill(env("EMAIL"))
  #password.fill(env("PASSWORD"))

Statement forms
---------------
  Assignment:     $name = "value"   (variables)
                  timeout = 30000   (settings)

  Function call:  command(arg1, arg2, ...)

  Element chain:  SELECTOR[n].action(arg1, ...)
                  SELECTOR.action(arg1, ...)

    The element chain is the primary way to interact with page elements.
    SELECTOR is any CSS selector. The optional [n] picks the nth match
    (0-based). action is a method like click, fill, assert_visible, etc.

    Examples:
        .nav-item[0].click()
        #email.fill("me@example.com")
        [name="q"].type("playwright")
        .results li[2].assert_text("Expected")

Arguments inside calls are comma-separated. Strings must be quoted with
double or single quotes. Variable references ($name) are left as-is and
resolved at runtime.
"""

import re
from dataclasses import dataclass

# Variable assignment:  $name = <value>
_VAR_ASSIGN = re.compile(r'^\$(\w+)\s*=\s*(.+)$')

# Setting assignment:   timeout = <value>  /  slow = <value>
_SETTING_ASSIGN = re.compile(r'^(timeout|slow)\s*=\s*(.+)$')

# Function call:        name(...)  — name ends at first '('
_FUNC_NAME = re.compile(r'^([a-z][a-z_0-9]*)\(')

# Method call inside a chain: .method(
_METHOD_CALL = re.compile(r'\.([a-z][a-z_0-9]*)\(')

# Optional trailing index inside a chain selector:  SELECTOR[n]
_TRAILING_INDEX = re.compile(r'^(.*)\[(\d+)\]$')

# Function definition:  func name($p1, $p2) {
_FUNC_DEF = re.compile(r'^func\s+([a-z][a-z_0-9]*)\s*\(([^)]*)\)\s*\{$')

# Semantic locator chain: text("...").action()  /  role("button", "Name").action()
# Supported locator types:
#   text("content")          — get_by_text()
#   role("role", "name")     — get_by_role()
#   label("text")            — get_by_label()
#   placeholder("text")      — get_by_placeholder()
#   testid("id")             — get_by_test_id()
#   alt("text")              — get_by_alt_text()
#   title("text")            — get_by_title()
#   xpath("expr")            — locator("xpath=...")
_LOCATOR_START = re.compile(r'^(text|role|label|placeholder|testid|alt|title|xpath)\s*\(')


@dataclass
class Line:
    number: int
    command: str   # function name, '__assign__', '__element__', or '__func_def__'
    args: list[str]
    raw: str
    body: 'list[Line] | None' = None


def tokenize(source: str) -> list[Line]:
    source = _strip_comments(source)
    raw_lines = list(enumerate(source.splitlines(), start=1))
    lines: list[Line] = []
    i = 0
    while i < len(raw_lines):
        lineno, raw = raw_lines[i]
        stripped = raw.strip()
        i += 1
        if not stripped or _is_comment(stripped):
            continue

        # Function definition: func name($p1, $p2) {
        m = _FUNC_DEF.match(stripped)
        if m:
            func_name = m.group(1)
            params_str = m.group(2).strip()
            params = [p.strip() for p in params_str.split(',') if p.strip()] if params_str else []
            for p in params:
                if not p.startswith('$'):
                    raise SyntaxError(
                        f'Line {lineno}: function parameter must start with $, got {p!r}'
                    )
            # Collect body lines until the closing '}'
            body_lines: list[Line] = []
            found_close = False
            while i < len(raw_lines):
                blineno, braw = raw_lines[i]
                bstripped = braw.strip()
                i += 1
                if bstripped == '}':
                    found_close = True
                    break
                if not bstripped or _is_comment(bstripped):
                    continue
                body_lines.append(_parse_line(blineno, bstripped, braw))
            if not found_close:
                raise SyntaxError(
                    f'Line {lineno}: function {func_name!r} — missing closing }}'
                )
            lines.append(
                Line(lineno, '__func_def__', [func_name] + params, raw, body=body_lines)
            )
            continue

        lines.append(_parse_line(lineno, stripped, raw))
    return lines


# ---------------------------------------------------------------------------
# Comment stripping
# ---------------------------------------------------------------------------

def _strip_comments(source: str) -> str:
    """Remove // line comments and /* */ block comments from *source*.

    String literals (single- or double-quoted) are respected — comment
    markers that appear inside a string are left untouched.
    All newline characters are preserved so that line numbers reported in
    error messages remain accurate after stripping.
    """
    out: list[str] = []
    i = 0
    n = len(source)
    in_string: str | None = None

    while i < n:
        ch = source[i]

        if in_string:
            out.append(ch)
            if ch == '\\' and i + 1 < n:
                # Escaped character — consume both to avoid treating \"
                # as the closing delimiter.
                out.append(source[i + 1])
                i += 2
            else:
                if ch == in_string:
                    in_string = None
                i += 1

        elif ch in ('"', "'"):
            in_string = ch
            out.append(ch)
            i += 1

        elif ch == '/' and i + 1 < n:
            nxt = source[i + 1]
            if nxt == '/':
                # Line comment: skip forward to end of line (keep the \n).
                i += 2
                while i < n and source[i] != '\n':
                    i += 1
            elif nxt == '*':
                # Block comment: skip until */, preserving newlines so
                # that line numbers stay correct.
                i += 2
                while i < n:
                    if source[i] == '*' and i + 1 < n and source[i + 1] == '/':
                        i += 2
                        break
                    if source[i] == '\n':
                        out.append('\n')
                    i += 1
            else:
                out.append(ch)
                i += 1

        else:
            out.append(ch)
            i += 1

    return ''.join(out)


def _is_comment(s: str) -> bool:
    """Return True if *s* is a legacy # comment line.

    A ``#`` comment requires a space, another ``#``, or end-of-string
    immediately after the hash — e.g. ``# note``, ``## heading``, ``#``.
    This lets CSS id selectors like ``#email.fill("value")`` pass through.
    ``//`` comments are already stripped by ``_strip_comments`` before this
    function is called, but the check is included here as a safety net.
    """
    if s.startswith('//'):
        return True
    if not s.startswith('#'):
        return False
    return len(s) == 1 or s[1] in ' \t#'


# ---------------------------------------------------------------------------
# Internal parsing helpers
# ---------------------------------------------------------------------------

def _parse_line(lineno: int, stripped: str, raw: str) -> Line:
    # Variable assignment: $name = value
    m = _VAR_ASSIGN.match(stripped)
    if m:
        name = '$' + m.group(1)
        value = _unquote(lineno, m.group(2).strip())
        return Line(lineno, '__assign__', [name, value], raw)

    # Setting assignment: timeout = value
    m = _SETTING_ASSIGN.match(stripped)
    if m:
        value = _unquote(lineno, m.group(2).strip())
        return Line(lineno, '__assign__', [m.group(1), value], raw)

    # Semantic locator chain: text("...").action() / role("button", "Name").action()
    # Checked BEFORE function calls so text(...).click() isn't swallowed as a bare call.
    result = _try_parse_locator_chain(lineno, stripped, raw)
    if result is not None:
        return result

    # Function call: name(args...)
    m = _FUNC_NAME.match(stripped)
    if m:
        name = m.group(1)
        rest = stripped[len(name):]          # "(args...)"
        args_str, trailing = _extract_parens(lineno, rest, raw)
        if trailing.strip():
            raise SyntaxError(
                f'Line {lineno}: unexpected characters after closing \')\' → {raw!r}'
            )
        args = _parse_args(lineno, args_str)
        return Line(lineno, name, args, raw)

    # Element chain syntax: SELECTOR[n].action(args)  or  SELECTOR.action(args)
    result = _try_parse_chain(lineno, stripped, raw)
    if result is not None:
        return result

    raise SyntaxError(
        f'Line {lineno}: invalid syntax — '
        f'use `$name = value` for variables, `command(...)` for calls, '
        f'or `selector.action(...)` for element chains → {raw!r}'
    )


def _try_parse_locator_chain(lineno: int, stripped: str, raw: str) -> 'Line | None':
    """Attempt to parse a semantic locator chain:

        text("New Candidate").click()
        role("button", "New Candidate").click()
        xpath("//button[@data-target='new-candidate']").click()
        text("Submit")[0].click()           # optional nth index

    Returns a Line with command '__locator__' if successful, None otherwise.
    Args layout: [locator_type, n_locator_args, *locator_args, index, action, *action_args]
      - locator_type:   'text' | 'role' | 'label' | 'placeholder' | 'testid' | 'alt' | 'title' | 'xpath'
      - n_locator_args: str(int) count of locator args that follow
      - locator_args:   the arguments passed to the locator function
      - index:          str(int) nth index, '-1' when not specified
      - action:         method name (click, fill, assert_visible, …)
      - action_args:    any arguments passed to the action
    """
    m = _LOCATOR_START.match(stripped)
    if not m:
        return None

    locator_type = m.group(1)
    paren_pos = stripped.index('(')
    locator_args_str, remainder = _extract_parens(lineno, stripped[paren_pos:], raw)
    locator_args = _parse_args(lineno, locator_args_str)
    remainder = remainder.lstrip()

    # Optional nth index: [n]
    idx_m = re.match(r'^\[(\d+)\](.*)', remainder)
    if idx_m:
        index = int(idx_m.group(1))
        remainder = idx_m.group(2).lstrip()
    else:
        index = -1

    # Required: .action(args)  — if absent this isn't a locator chain, fall through.
    action_m = re.match(r'^\.([a-z][a-z_0-9]*)\(', remainder)
    if not action_m:
        return None

    action = action_m.group(1)
    action_paren_pos = remainder.index('(')
    action_args_str, trailing = _extract_parens(lineno, remainder[action_paren_pos:], raw)
    if trailing.strip():
        raise SyntaxError(
            f'Line {lineno}: unexpected characters after closing \')\' → {raw!r}'
        )

    action_args = _parse_args(lineno, action_args_str)
    n = str(len(locator_args))
    args = [locator_type, n] + locator_args + [str(index), action] + action_args
    return Line(lineno, '__locator__', args, raw)


def _try_parse_chain(lineno: int, stripped: str, raw: str) -> 'Line | None':
    """Attempt to parse SELECTOR[n].action(args) chain syntax.

    Returns a Line with command '__element__' if successful, None otherwise.
    Args layout: [selector, index_str, action, *action_args]
      - selector:   CSS selector string
      - index_str:  '0', '1', ... or '-1' when no index specified
      - action:     method name  (click, fill, assert_visible, ...)
      - action_args: any arguments passed to the action
    """
    method_matches = list(_METHOD_CALL.finditer(stripped))
    if not method_matches:
        return None

    # Use the last .method( occurrence as the action call.
    m = method_matches[-1]
    action = m.group(1)
    action_dot_pos = m.start()   # position of '.'
    paren_pos = m.end() - 1      # position of '('

    # Everything before the '.' is the selector (plus optional [n]).
    selector_part = stripped[:action_dot_pos]
    if not selector_part:
        return None  # bare .method() with no selector — not a valid chain

    # Detect trailing index: SELECTOR[n]
    idx_m = _TRAILING_INDEX.match(selector_part)
    if idx_m:
        selector = idx_m.group(1)
        index = idx_m.group(2)
    else:
        selector = selector_part
        index = '-1'

    if not selector:
        return None

    # Extract the action's parenthesised args using the balanced-paren parser.
    args_str, trailing = _extract_parens(lineno, stripped[paren_pos:], raw)
    if trailing.strip():
        raise SyntaxError(
            f'Line {lineno}: unexpected characters after closing \')\' → {raw!r}'
        )

    action_args = _parse_args(lineno, args_str)
    args = [selector, index, action] + action_args
    return Line(lineno, '__element__', args, raw)


def _extract_parens(lineno: int, s: str, raw: str) -> tuple[str, str]:
    """Return (content_inside_outer_parens, remainder_after_closing_paren)."""
    assert s[0] == '('
    depth = 0
    in_string: str | None = None
    i = 0
    while i < len(s):
        ch = s[i]
        if in_string:
            if ch == '\\' and i + 1 < len(s):
                i += 2
                continue
            if ch == in_string:
                in_string = None
        elif ch in ('"', "'"):
            in_string = ch
        elif ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0:
                return s[1:i], s[i + 1:]
        i += 1
    raise SyntaxError(f'Line {lineno}: unmatched \'(\' → {raw!r}')


def _parse_args(lineno: int, args_str: str) -> list[str]:
    """Parse comma-separated, optionally-quoted function arguments.

    Handles nested calls (e.g. ``random_number(1, 100)``) by tracking
    parenthesis depth — commas inside nested parens are not treated as
    argument separators.
    """
    args_str = args_str.strip()
    if not args_str:
        return []

    args: list[str] = []
    current: list[str] = []
    in_string: str | None = None
    depth = 0  # paren depth for nested expressions such as random_number(1, 100)
    i = 0

    while i < len(args_str):
        ch = args_str[i]
        if in_string:
            if ch == '\\' and i + 1 < len(args_str):
                current.append(args_str[i + 1])
                i += 2
                continue
            if ch == in_string:
                in_string = None
            else:
                current.append(ch)
        elif ch in ('"', "'"):
            if depth > 0:
                # Inside a nested call — keep quotes so the token is preserved.
                current.append(ch)
            in_string = ch
        elif ch == '(' :
            depth += 1
            current.append(ch)
        elif ch == ')':
            depth -= 1
            current.append(ch)
        elif ch == ',' and depth == 0:
            args.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1

    if in_string:
        raise SyntaxError(f'Line {lineno}: unterminated string literal')

    last = ''.join(current).strip()
    if last:
        args.append(last)

    return args


def _unquote(lineno: int, text: str) -> str:
    """Strip surrounding quotes from a single value, or return it bare."""
    if len(text) >= 2 and text[0] in ('"', "'") and text[-1] == text[0]:
        return text[1:-1]
    if not text:
        raise SyntaxError(f'Line {lineno}: empty value in assignment')
    return text
