"""Random mock-data generators for bdr scripts.

Resolved at runtime inside ``_resolve()`` — any argument position that accepts
a string also accepts one of these calls, e.g.::

    $email    = random_email()
    $password = random_password(16)
    $age      = random_number(18, 65)

    fill("#email",    random_email())
    fill("#password", random_password(16))
"""

from __future__ import annotations

import random
import re
import string
import uuid


class MockError(Exception):
    """Raised when a ``random_*()`` call has bad arguments."""


# ---------------------------------------------------------------------------
# Name / domain data
# ---------------------------------------------------------------------------

_FIRST_NAMES = [
    "Alice", "Bob", "Carol", "David", "Emma", "Frank", "Grace", "Henry",
    "Isabel", "Jack", "Karen", "Liam", "Mia", "Noah", "Olivia", "Paul",
    "Quinn", "Rachel", "Samuel", "Tara", "Uma", "Victor", "Wendy", "Xander",
    "Yara", "Zoe", "Aaron", "Beth", "Carlos", "Diana", "Ethan", "Fiona",
]

_LAST_NAMES = [
    "Adams", "Baker", "Clark", "Davis", "Evans", "Foster", "Garcia", "Harris",
    "Ingram", "Jones", "King", "Lopez", "Miller", "Nelson", "Owen", "Parker",
    "Quinn", "Reed", "Smith", "Taylor", "Underwood", "Vasquez", "Walker",
    "Xavier", "Young", "Zhang", "Brown", "Chen", "Diaz", "Edwards",
]

_DOMAINS = ["example.com", "testmail.org", "mockuser.net", "devtest.io"]

# ---------------------------------------------------------------------------
# Token detection
# ---------------------------------------------------------------------------

# Matches:  random_email()  /  random_string(12)  /  random_number(1, 100)
_MOCK_CALL = re.compile(r'^(random_[a-z_]+)\(([^)]*)\)$')


def resolve_mock(token: str, lineno: int) -> str | None:
    """Return a generated value if *token* is a ``random_*()`` call.

    Returns ``None`` when the token is not a mock call at all (so the caller
    can continue with normal resolution).  Raises ``MockError`` for recognised
    calls whose arguments are invalid.
    """
    m = _MOCK_CALL.match(token.strip())
    if not m:
        return None

    func = m.group(1)
    raw = m.group(2).strip()
    # Split on commas, but only when not inside quotes (handles quoted defaults).
    args = [a.strip() for a in raw.split(',') if a.strip()] if raw else []

    return _dispatch(func, args, lineno)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def _dispatch(func: str, args: list[str], lineno: int) -> str:
    if func == "random_email":
        _expect(func, args, 0, lineno)
        user = _chars(random.randint(5, 10), string.ascii_lowercase + string.digits)
        return f"{user}@{random.choice(_DOMAINS)}"

    if func == "random_name":
        _expect(func, args, 0, lineno)
        return f"{random.choice(_FIRST_NAMES)} {random.choice(_LAST_NAMES)}"

    if func == "random_first_name":
        _expect(func, args, 0, lineno)
        return random.choice(_FIRST_NAMES)

    if func == "random_last_name":
        _expect(func, args, 0, lineno)
        return random.choice(_LAST_NAMES)

    if func == "random_username":
        length = _one_int(func, args, lineno, default=8)
        return _chars(length, string.ascii_lowercase + string.digits)

    if func == "random_string":
        length = _one_int(func, args, lineno, default=12)
        return _chars(length, string.ascii_letters + string.digits)

    if func == "random_password":
        length = _one_int(func, args, lineno, default=12)
        if length < 4:
            raise MockError(
                f"Line {lineno}: random_password() length must be at least 4, got {length}"
            )
        symbols = "!@#$%^&*"
        pool = string.ascii_letters + string.digits + symbols
        # Guarantee at least one of each required character class.
        core = _chars(length - 3, pool)
        forced = (
            random.choice(string.ascii_uppercase)
            + random.choice(string.digits)
            + random.choice(symbols)
        )
        result = list(core + forced)
        random.shuffle(result)
        return ''.join(result)

    if func == "random_number":
        if len(args) == 0:
            return str(random.randint(0, 9999))
        if len(args) == 1:
            hi = _to_int(func, args[0], lineno)
            return str(random.randint(0, hi))
        if len(args) == 2:
            lo = _to_int(func, args[0], lineno)
            hi = _to_int(func, args[1], lineno)
            if lo > hi:
                raise MockError(
                    f"Line {lineno}: random_number() min ({lo}) must be <= max ({hi})"
                )
            return str(random.randint(lo, hi))
        raise MockError(
            f"Line {lineno}: random_number() takes 0, 1, or 2 arguments, got {len(args)}"
        )

    if func == "random_phone":
        _expect(func, args, 0, lineno)
        area = random.randint(200, 999)
        mid  = random.randint(100, 999)
        end  = random.randint(1000, 9999)
        return f"{area}-{mid}-{end}"

    if func == "random_uuid":
        _expect(func, args, 0, lineno)
        return str(uuid.uuid4())

    raise MockError(
        f"Line {lineno}: unknown mock function '{func}()'\n"
        f"  Available: random_email, random_name, random_first_name, random_last_name,\n"
        f"             random_username, random_string, random_password,\n"
        f"             random_number, random_phone, random_uuid"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chars(length: int, pool: str) -> str:
    return ''.join(random.choices(pool, k=length))


def _expect(func: str, args: list[str], count: int, lineno: int) -> None:
    if len(args) != count:
        raise MockError(
            f"Line {lineno}: {func}() takes {count} argument(s), got {len(args)}"
        )


def _one_int(func: str, args: list[str], lineno: int, default: int) -> int:
    if len(args) == 0:
        return default
    if len(args) == 1:
        return _to_int(func, args[0], lineno)
    raise MockError(
        f"Line {lineno}: {func}() takes 0 or 1 argument, got {len(args)}"
    )


def _to_int(func: str, val: str, lineno: int) -> int:
    try:
        return int(val)
    except ValueError:
        raise MockError(
            f"Line {lineno}: {func}() expects an integer argument, got '{val}'"
        )
