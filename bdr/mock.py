"""Random mock-data generators for bdr scripts.

Resolved at runtime inside ``_resolve()`` — any argument position that accepts
a string also accepts one of these calls, e.g.::

    $email    = random_email()
    $password = random_password(16)
    $phone    = random_phone()

    #email.fill(random_email())
    #password.fill(random_password(16))
    #zip.fill(random_zip())
"""

from __future__ import annotations

import datetime
import random
import re
import string
import uuid


class MockError(Exception):
    """Raised when a ``random_*()`` call has bad arguments."""


# ---------------------------------------------------------------------------
# Name data
# ---------------------------------------------------------------------------

_FIRST_NAMES = [
    "Alice", "Bob", "Carol", "David", "Emma", "Frank", "Grace", "Henry",
    "Isabel", "Jack", "Karen", "Liam", "Mia", "Noah", "Olivia", "Paul",
    "Quinn", "Rachel", "Samuel", "Tara", "Uma", "Victor", "Wendy", "Xander",
    "Yara", "Zoe", "Aaron", "Beth", "Carlos", "Diana", "Ethan", "Fiona",
    "George", "Hannah", "Ivan", "Julia", "Kevin", "Laura", "Marcus", "Nina",
]

_LAST_NAMES = [
    "Adams", "Baker", "Clark", "Davis", "Evans", "Foster", "Garcia", "Harris",
    "Ingram", "Jones", "King", "Lopez", "Miller", "Nelson", "Owen", "Parker",
    "Quinn", "Reed", "Smith", "Taylor", "Underwood", "Vasquez", "Walker",
    "Xavier", "Young", "Zhang", "Brown", "Chen", "Diaz", "Edwards", "Flynn",
    "Gomez", "Hayes", "Irving", "James", "Klein", "Lewis", "Moore", "Nash",
]

# ---------------------------------------------------------------------------
# Address data
# ---------------------------------------------------------------------------

_STREET_NAMES = [
    "Main", "Oak", "Maple", "Cedar", "Pine", "Elm", "Washington", "Park",
    "Lake", "Hill", "River", "Sunset", "Highland", "Forest", "Meadow",
    "Spring", "Valley", "Willow", "Birch", "Chestnut", "Broadway", "Lincoln",
    "Jefferson", "Adams", "Madison", "Monroe", "Jackson", "Harrison",
]

_STREET_SUFFIXES = [
    "Street", "Avenue", "Road", "Boulevard", "Drive", "Lane", "Way",
    "Court", "Place", "Circle", "Trail", "Parkway",
]

_CITIES = [
    "Springfield", "Riverside", "Fairview", "Madison", "Georgetown", "Salem",
    "Greenville", "Franklin", "Centerville", "Bristol", "Clinton", "Dayton",
    "Lexington", "Marion", "Oxford", "Troy", "Burlington", "Dover",
    "Hamilton", "Milford", "Newark", "Newport", "Richmond", "Rochester",
    "Winchester", "Arlington", "Ashland", "Auburn", "Bedford", "Camden",
]

_STATES: list[tuple[str, str]] = [
    ("Alabama", "AL"), ("Alaska", "AK"), ("Arizona", "AZ"),
    ("Arkansas", "AR"), ("California", "CA"), ("Colorado", "CO"),
    ("Connecticut", "CT"), ("Delaware", "DE"), ("Florida", "FL"),
    ("Georgia", "GA"), ("Hawaii", "HI"), ("Idaho", "ID"),
    ("Illinois", "IL"), ("Indiana", "IN"), ("Iowa", "IA"),
    ("Kansas", "KS"), ("Kentucky", "KY"), ("Louisiana", "LA"),
    ("Maine", "ME"), ("Maryland", "MD"), ("Massachusetts", "MA"),
    ("Michigan", "MI"), ("Minnesota", "MN"), ("Mississippi", "MS"),
    ("Missouri", "MO"), ("Montana", "MT"), ("Nebraska", "NE"),
    ("Nevada", "NV"), ("New Hampshire", "NH"), ("New Jersey", "NJ"),
    ("New Mexico", "NM"), ("New York", "NY"), ("North Carolina", "NC"),
    ("North Dakota", "ND"), ("Ohio", "OH"), ("Oklahoma", "OK"),
    ("Oregon", "OR"), ("Pennsylvania", "PA"), ("Rhode Island", "RI"),
    ("South Carolina", "SC"), ("South Dakota", "SD"), ("Tennessee", "TN"),
    ("Texas", "TX"), ("Utah", "UT"), ("Vermont", "VT"), ("Virginia", "VA"),
    ("Washington", "WA"), ("West Virginia", "WV"), ("Wisconsin", "WI"),
    ("Wyoming", "WY"),
]

_COUNTRIES = [
    "United States", "Canada", "United Kingdom", "Australia", "Germany",
    "France", "Japan", "Brazil", "India", "Mexico", "Italy", "Spain",
    "Netherlands", "Sweden", "Norway", "Denmark", "Finland", "Switzerland",
    "Austria", "New Zealand",
]

# ---------------------------------------------------------------------------
# Company / internet / word data
# ---------------------------------------------------------------------------

_COMPANIES = [
    "Acme Corp", "Apex Solutions", "Blue Horizon Inc", "Bright Path LLC",
    "Cedar Group", "Delta Systems", "Echo Technologies", "Falcon Dynamics",
    "Global Ventures", "Harbor Tech", "Ironwood Partners", "Jade Innovations",
    "Keystone Labs", "Luminary Co", "Nexus Digital", "Orbit Software",
    "Pinnacle Works", "Quantum Holdings", "Redwood Consulting", "Summit Group",
    "Tidal Ventures", "Unity Systems", "Vertex Solutions", "Wavefront Tech",
    "Zenith Labs", "Atlas Corp", "Beacon Works", "Catalyst Inc",
]

_DOMAINS = ["example.com", "testmail.org", "mockuser.net", "devtest.io",
            "demo.app", "staging.dev", "fakeinbox.com"]

_URL_SLUGS = [
    "test", "demo", "staging", "mock", "dev", "sample", "preview",
    "beta", "alpha", "sandbox", "temp", "trial",
]

_WORDS = [
    "apple", "bridge", "cloud", "dragon", "ember", "falcon", "garden",
    "harbor", "island", "jungle", "knight", "lantern", "mountain", "nebula",
    "ocean", "planet", "quest", "river", "storm", "thunder", "universe",
    "village", "whisper", "zenith", "anchor", "beacon", "castle", "desert",
    "eclipse", "forest", "glacier", "horizon", "ivory", "jasmine", "karma",
    "lotus", "marble", "nomad", "onyx", "prism", "quartz", "raven", "sapphire",
    "titan", "ultra", "vapor", "walrus", "xenon", "yacht", "zephyr",
]

_SENTENCE_SUBJECTS = [
    "The quick fox", "A rolling stone", "Every cloud", "The early bird",
    "Fortune", "Knowledge", "Time", "Actions", "Better ideas", "Hard work",
]

_SENTENCE_PREDICATES = [
    "jumps over the lazy dog.", "gathers no moss.", "has a silver lining.",
    "catches the worm.", "favors the bold.", "is power.", "flies quickly.",
    "speak louder than words.", "often win.", "pays off.",
]

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
    raw  = m.group(2).strip()
    args = [a.strip() for a in raw.split(',') if a.strip()] if raw else []

    return _dispatch(func, args, lineno)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def _dispatch(func: str, args: list[str], lineno: int) -> str:

    # ── Identity ─────────────────────────────────────────────────────────────

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

    if func == "random_company":
        _expect(func, args, 0, lineno)
        return random.choice(_COMPANIES)

    # ── Passwords / strings ──────────────────────────────────────────────────

    if func == "random_password":
        length = _one_int(func, args, lineno, default=12)
        if length < 4:
            raise MockError(
                f"Line {lineno}: random_password() length must be at least 4, got {length}"
            )
        symbols = "!@#$%^&*"
        pool = string.ascii_letters + string.digits + symbols
        # Guarantee at least one uppercase, one digit, one symbol.
        core = _chars(length - 3, pool)
        forced = (
            random.choice(string.ascii_uppercase)
            + random.choice(string.digits)
            + random.choice(symbols)
        )
        result = list(core + forced)
        random.shuffle(result)
        return ''.join(result)

    if func == "random_string":
        # Mixed letters + digits — general purpose
        length = _one_int(func, args, lineno, default=12)
        return _chars(length, string.ascii_letters + string.digits)

    if func == "random_alpha":
        # Letters only (a-z A-Z)
        length = _one_int(func, args, lineno, default=8)
        return _chars(length, string.ascii_letters)

    if func == "random_digits":
        # Digit characters only — useful for PIN codes, verification codes, etc.
        length = _one_int(func, args, lineno, default=6)
        # Ensure the first character is never 0 so the result looks like a number.
        first = random.choice(string.digits[1:])
        rest  = _chars(length - 1, string.digits) if length > 1 else ""
        return first + rest

    if func == "random_hex":
        # Lowercase hex string — useful for tokens, hashes, API keys, etc.
        length = _one_int(func, args, lineno, default=16)
        return _chars(length, "0123456789abcdef")

    if func == "random_uuid":
        _expect(func, args, 0, lineno)
        return str(uuid.uuid4())

    # ── Numbers ──────────────────────────────────────────────────────────────

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

    # ── Contact ──────────────────────────────────────────────────────────────

    if func == "random_phone":
        # US format: 800-555-0100 to 800-555-0199
        _expect(func, args, 0, lineno)
        area = random.randint(200, 999)
        mid  = random.randint(200, 999)
        end  = random.randint(1000, 9999)
        return f"{area}-{mid}-{end}"

    if func == "random_phone_intl":
        # International format: +1 800-555-0100
        _expect(func, args, 0, lineno)
        area = random.randint(200, 999)
        mid  = random.randint(200, 999)
        end  = random.randint(1000, 9999)
        return f"+1 {area}-{mid}-{end}"

    # ── Address ──────────────────────────────────────────────────────────────

    if func == "random_address":
        # Street address: "742 Elm Street"
        _expect(func, args, 0, lineno)
        num    = random.randint(1, 9999)
        name   = random.choice(_STREET_NAMES)
        suffix = random.choice(_STREET_SUFFIXES)
        return f"{num} {name} {suffix}"

    if func == "random_city":
        _expect(func, args, 0, lineno)
        return random.choice(_CITIES)

    if func == "random_state":
        # Full name: "Texas"
        _expect(func, args, 0, lineno)
        return random.choice(_STATES)[0]

    if func == "random_state_abbr":
        # Abbreviation: "TX"
        _expect(func, args, 0, lineno)
        return random.choice(_STATES)[1]

    if func == "random_zip":
        # 5-digit US zip code: "73301"
        _expect(func, args, 0, lineno)
        return f"{random.randint(10000, 99999)}"

    if func == "random_country":
        _expect(func, args, 0, lineno)
        return random.choice(_COUNTRIES)

    # ── Dates ────────────────────────────────────────────────────────────────

    if func == "random_date":
        # Random date within the last 10 years — ISO format YYYY-MM-DD
        _expect(func, args, 0, lineno)
        today    = datetime.date.today()
        past     = today - datetime.timedelta(days=365 * 10)
        delta    = (today - past).days
        result   = past + datetime.timedelta(days=random.randint(0, delta))
        return result.strftime("%Y-%m-%d")

    if func == "random_date_past":
        # Random date from the past — formatted MM/DD/YYYY (common form format)
        _expect(func, args, 0, lineno)
        today  = datetime.date.today()
        past   = today - datetime.timedelta(days=365 * 20)
        delta  = (today - past).days
        result = past + datetime.timedelta(days=random.randint(0, delta - 1))
        return result.strftime("%m/%d/%Y")

    if func == "random_date_future":
        # Random date in the next 5 years — formatted MM/DD/YYYY
        _expect(func, args, 0, lineno)
        today  = datetime.date.today()
        future = today + datetime.timedelta(days=365 * 5)
        delta  = (future - today).days
        result = today + datetime.timedelta(days=random.randint(1, delta))
        return result.strftime("%m/%d/%Y")

    if func == "random_card_expiry":
        # Credit card expiry: MM/YY, always in the future
        _expect(func, args, 0, lineno)
        today      = datetime.date.today()
        months_out = random.randint(3, 60)       # 3 months to 5 years out
        year       = today.year + (today.month - 1 + months_out) // 12
        month      = (today.month - 1 + months_out) % 12 + 1
        return f"{month:02d}/{str(year)[-2:]}"

    # ── Payment ──────────────────────────────────────────────────────────────

    if func == "random_credit_card":
        # Luhn-valid 16-digit Visa-format card number (starts with 4)
        _expect(func, args, 0, lineno)
        digits    = [4] + [random.randint(0, 9) for _ in range(14)] + [0]
        digits[-1] = _luhn_check_digit(digits)
        return ''.join(str(d) for d in digits)

    if func == "random_cvv":
        # 3-digit card security code
        _expect(func, args, 0, lineno)
        return f"{random.randint(100, 999)}"

    # ── Web / network ────────────────────────────────────────────────────────

    if func == "random_url":
        _expect(func, args, 0, lineno)
        slug   = random.choice(_URL_SLUGS)
        suffix = _chars(4, string.ascii_lowercase + string.digits)
        domain = random.choice(_DOMAINS)
        return f"https://{slug}-{suffix}.{domain}"

    if func == "random_ip":
        # IPv4 address in the non-reserved range
        _expect(func, args, 0, lineno)
        return ".".join(str(random.randint(1, 254)) for _ in range(4))

    if func == "random_color":
        # CSS hex color: "#a3f2c1"
        _expect(func, args, 0, lineno)
        return "#{:06x}".format(random.randint(0, 0xFFFFFF))

    # ── Text ─────────────────────────────────────────────────────────────────

    if func == "random_word":
        _expect(func, args, 0, lineno)
        return random.choice(_WORDS)

    if func == "random_sentence":
        _expect(func, args, 0, lineno)
        subject   = random.choice(_SENTENCE_SUBJECTS)
        predicate = random.choice(_SENTENCE_PREDICATES)
        return f"{subject} {predicate}"

    raise MockError(
        f"Line {lineno}: unknown random function '{func}()'\n"
        f"  Identity:   random_name, random_first_name, random_last_name,\n"
        f"              random_username, random_email, random_company\n"
        f"  Strings:    random_password(len), random_string(len), random_alpha(len),\n"
        f"              random_digits(len), random_hex(len), random_uuid\n"
        f"  Numbers:    random_number, random_number(max), random_number(min, max)\n"
        f"  Contact:    random_phone, random_phone_intl\n"
        f"  Address:    random_address, random_city, random_state, random_state_abbr,\n"
        f"              random_zip, random_country\n"
        f"  Dates:      random_date, random_date_past, random_date_future,\n"
        f"              random_card_expiry\n"
        f"  Payment:    random_credit_card, random_cvv\n"
        f"  Web:        random_url, random_ip, random_color\n"
        f"  Text:       random_word, random_sentence"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chars(length: int, pool: str) -> str:
    return ''.join(random.choices(pool, k=length))


def _luhn_check_digit(digits: list[int]) -> int:
    """Return the Luhn check digit for a list of digits whose last entry is 0."""
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i == 0:
            continue               # skip the placeholder last digit
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - (total % 10)) % 10


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
