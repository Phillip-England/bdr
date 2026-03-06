# bdr

bdr is a scripting language for browser automation. Write `.bdr` scripts using CSS selectors to drive a real browser.

```
# login.bdr
$url = "https://example.com/login"

load($url)
#email.fill("me@example.com")
#password.fill("hunter2")
#submit.click()
assert_title("Dashboard")
screenshot("done.png")
```

```bash
bdr run login.bdr
```

---

## Installation

bdr requires [uv](https://docs.astral.sh/uv/). If you don't have it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Install globally (recommended)

```bash
make install
```

This installs `bdr` as a standalone tool on your PATH and downloads the Chromium browser. After this, run `bdr` from anywhere.

If you don't have the repo yet:

```bash
uv tool install bdr
bdr setup
```

### Install for development

```bash
git clone https://github.com/yourname/bdr
cd bdr
make dev
```

`make dev` runs `uv sync` and `bdr setup`. Use `uv run bdr` to run the local version while developing.

### Build a standalone binary

```bash
make bundle
```

Produces `dist/bdr` — a single self-contained file with Python and all dependencies baked in. Copy it to any machine (no Python or uv needed), then:

```bash
./bdr setup      # download browser binaries once
./bdr run script.bdr
```

---

## The element chain syntax

CSS selectors are the primary way to interact with elements in bdr. The syntax is:

```
SELECTOR.action()
SELECTOR.action(argument)
SELECTOR[n].action()        # pick the nth match (0-based)
```

**Examples:**

```
#submit.click()                      # click by id
.btn-primary.click()                 # click by class
[name="q"].fill("playwright")        # fill by attribute
.nav-item[0].click()                 # click the first nav item
.result[2].assert_text("Expected")   # check text of the third result
```

bdr automatically waits for each element to appear before acting — no manual waits needed for standard interactions.

---

## Language reference

bdr scripts are plain `.bdr` text files. Lines starting with `#` are comments. Blank lines are ignored.

---

### Comments

Three comment styles are supported:

```
// This is a line comment — from // to the end of the line

/* This is a block comment.
   It can span multiple lines. */

# This is the legacy line comment style — also still works
```

Comments can appear on their own line or at the end of any statement:

```
load("localhost:3000")       // navigate to the dev server

/* fill credentials from variables */
#email.fill($email)
#password.fill($password)    // clear then fill
#submit.click()
```

The `//` inside string values (like `"https://example.com"`) is never treated as a comment — only `//` outside of quotes starts a comment.

---

### Variables

Declare a variable with `$name = value`. The `$` prefix is **required** — both when declaring and when using it.

```
$url = "https://staging.example.com"
$user = "me@example.com"

load($url)
#email.fill($user)
log("Testing against", $url)
```

> **Common mistake:** writing `url = "https://..."` instead of `$url = "https://..."`.
> Without the `$`, bdr treats it as a setting name (like `timeout`) and raises an error.

Variables are global to the session — any variable set in a parent script or a previously `exec`'d script is visible to all subsequent scripts.

Using an undefined variable raises an error immediately.

---

### Settings

Settings use bare `name = value` syntax — **no `$` prefix**. Both can be changed at any point in a script.

#### `timeout`

How long bdr waits for an element to appear before failing, in milliseconds.

```
timeout = 10000    // 10 seconds — wait longer for slow pages
timeout = 5000     // 5 seconds  — fail faster during development
```

Default is `30000` ms (30 seconds). The `--timeout` CLI flag sets the initial value.

#### `slow`

Pause between every action, in seconds. This is a buffer applied automatically after each command — no need to manually insert `wait()` calls throughout your script.

```
slow = 0.5     // half-second gap between every action
slow = 1       // one full second — good for watching the browser step through
slow = 0       // no pause (default)
```

Default is `0` (no pause). Can be set or changed at any point in a script — only commands that follow the setting are affected.

```
// login.bdr
timeout = 5000
slow = 0.3          // 300ms buffer between every action

load("localhost:3000")
#email.fill("me@example.com")     // waits 0.3s after this
#password.fill("hunter2")         // waits 0.3s after this
#submit.click()                   // waits 0.3s after this
```

The `--slow` CLI flag sets the initial value, which the script can override:

```bash
bdr run script.bdr --slow 0.5    // 500ms between commands
```

---

### Navigation

```
load("https://example.com")
load("localhost:3000")          # http:// is added automatically
load($url)                      # works with variables
load_clipboard()                # reads URL from your system clipboard

back()
forward()
refresh()
```

`load_clipboard()` accepts the same URL formats as `load()`. If the clipboard has
`localhost:3000`, bdr navigates to `http://localhost:3000`.

---

### Element chains — interaction

```
#submit.click()
.btn-primary.click()
[type="submit"].click()

#email.fill("me@example.com")          # clears then fills
.search-input.fill($query)             # works with variables

#search.type("playwright")             # types character by character

#country.select("United States")       # pick a <select> option by visible label text

[name="agree"].check()                 # check a checkbox
[name="agree"].uncheck()               # uncheck a checkbox

#tooltip-target.hover()
#first-field.focus()

.cta-button.scroll_to()                # scroll element into view

input[type="file"].upload("./doc.pdf") # attach a file (see File upload below)
canvas.draw()                          # sign a signature pad (see Drawing below)
```

---

### File upload

Use `.upload()` on an `<input type="file">` element to attach local files without touching the OS file-picker dialog.

```
input[type="file"].upload("./documents/contract.pdf")
#doc-input.upload("./id-front.jpg", "./id-back.jpg")   // multiple files at once
$path = "./signed-form.pdf"
#upload-field.upload($path)                             // works with variables
```

- Paths are resolved relative to the **script's directory** (not `cwd`).
- An error is raised immediately if the file does not exist.
- Upload bypasses the native file-picker — no `press("Enter")` or dialog handling needed.

---

### Drawing / signature pads

Use `.draw()` on a `<canvas>` or signature-pad element to simulate a handwritten signature using mouse events.

```
// Default — draws a natural wave across the full element width
canvas.draw()
#signature-canvas.draw()

// Custom path — space-separated "x,y" pixel offsets relative to the element's top-left corner
canvas.draw("10,60 60,20 120,70 180,25 240,55")
```

- The element must be visible before `.draw()` is called; add `.wait_visible()` if the canvas appears after a user interaction.
- Works with popular signature libraries (e.g. `signature_pad.js`, DocuSign embedded pads) — just target the `<canvas>` element directly.
- Combine with `screenshot("sig-check.png")` to verify the result visually.

**Pattern for a legal-document signature flow:**

```
load("https://app.example.com/sign/abc123")
#agree-checkbox.check()
#signature-canvas.wait_visible()
#signature-canvas.draw()            // sign
#submit-signature.click()
#confirmation.wait()
screenshot("signed.png")
```

---

### Dropdowns (`<select>` elements)

There are three ways to choose an option from a `<select>` dropdown, depending on what you know about the element.

#### `.select("label")` — by visible text *(most common)*

Picks the option whose text the user can read in the dropdown. Use this when you know what the page shows.

```
#country.select("United States")
#state.select("California")
#size.select("Large")

// works with variables and random generators too
$country = "Canada"
#country.select($country)
#country.select(random_country())
```

#### `.select_value("value")` — by HTML value attribute

Picks the option whose `value=` attribute matches. Use this when the visible label and the underlying value differ — for example a dropdown that shows `"United States"` but has `value="us"` in the HTML.

```html
<!-- example HTML -->
<select id="country">
  <option value="us">United States</option>
  <option value="ca">Canada</option>
  <option value="gb">United Kingdom</option>
</select>
```

```
#country.select_value("us")    // selects "United States"
#country.select_value("ca")    // selects "Canada"
```

#### `.select_index(n)` — by position

Picks the option at position `n`, counting from 0. Use this when you don't know the label or value, or when you just want the first/last option.

```
#size.select_index(0)    // first option
#size.select_index(1)    // second option
#size.select_index(2)    // third option
```

#### Choosing which to use

| You know… | Use |
|---|---|
| The text shown in the dropdown | `.select("label")` |
| The HTML `value=` attribute | `.select_value("val")` |
| The position in the list | `.select_index(n)` |

If `.select()` fails, inspect the HTML to check whether the visible label matches the `value=` attribute — they are often different (e.g. label `"United States"` with `value="US"`). Switch to `.select_value()` in that case.

#### Full signup form example with dropdowns

```
load("https://example.com/signup")

#full-name.fill(random_name())
#email.fill(random_email())
#password.fill(random_password(16))

// dropdowns
#country.select("United States")
#state.select(random_state())            // pick a random US state by name
#state-abbr.select_value(random_state_abbr())   // or by abbreviation value
#shirt-size.select_index(0)             // just pick the first size option

#submit.click()
```

---

### Element chains — indexing

When a selector matches multiple elements, add `[n]` (0-based) to pick one:

```
.nav-item[0].click()          # first nav item
.result[2].assert_text("Hi")  # third result
li[4].click()                 # fifth list item
```

---

### Element chains — waiting

```
#modal.wait()                  # wait for element to appear in DOM
.spinner.wait_visible()        # wait for element to be visible
```

---

### Element chains — assertions

All element assertions auto-wait for the element to appear before checking.

#### Text content

```
#heading.assert_text("Welcome")              # text contains value
#heading.assert_text_equals("Welcome back")  # exact match
```

#### Visibility and existence

```
#modal.assert_visible()
#error-banner.assert_hidden()
.lazy-widget.assert_exists()
.old-element.assert_not_exists()
```

#### Element state

```
#submit.assert_enabled()
#submit.assert_disabled()
[name="agree"].assert_checked()
[name="newsletter"].assert_unchecked()
```

#### Input value and attributes

```
#email.assert_value("me@example.com")
#link.assert_attribute("href", "/home")
#banner.assert_class("is-success")
.result-item.assert_count(10)          # counts all matches, index is ignored
```

---

### Page-level waiting

```
wait(2)                              # sleep 2 seconds unconditionally
wait_for_text("Welcome back")        # wait for text to appear anywhere on page
wait_until_loaded("/dashboard")      # wait until URL contains path and page is loaded
wait_until_loaded("https://example.com/dashboard")
```

---

### Page-level assertions

```
assert_title("Dashboard")
assert_title_equals("My App — Dashboard")

assert_url("example.com/dashboard")
assert_url_equals("https://example.com/dashboard")

assert_page_contains("Free trial")
```

---

### Keyboard

```
press("Enter")
press("Tab")
press("Escape")
```

---

### Scrolling

```
scroll_up()
scroll_down()
.footer.scroll_to()     # scroll an element into view (element chain)
```

---

### Script composition

`exec()` runs another `.bdr` file inline, sharing the same browser session, variables, and timeout.

```
exec("./steps/login.bdr")
exec("../shared/teardown.bdr")
```

Use `exec` to build suites:

```
# suite.bdr
timeout = 15000
$env = "https://staging.example.com"

exec("./tests/login.bdr")
exec("./tests/checkout.bdr")
exec("./tests/smoke.bdr")

log("All tests passed")
```

`bdr check suite.bdr` validates the entire chain without launching a browser. Circular imports are detected and reported as an error.

---

### Functions

Functions let you define reusable blocks of commands and call them anywhere in your script.

```
func login($user, $pass) {
  #email.fill($user)
  #password.fill($pass)
  #submit.click()
  #dashboard.wait()
}

load("https://example.com/login")
login("me@example.com", "hunter2")
```

#### Defining a function

```
func name($param1, $param2) {
  // body — any valid bdr commands
  SELECTOR.action($param1)
  command($param2)
}
```

- The function name uses lowercase letters, digits, and underscores.
- Parameters start with `$` and are available as local variables inside the body.
- The opening `{` must be on the same line as `func`.
- Functions can be defined anywhere in a script and called before or after the definition.

#### Calling a function

Functions are called exactly like built-in commands:

```
login("me@example.com", "hunter2")
fill_search_form($query)
do_checkout()
```

Arguments can be literals, variables, or random generators:

```
login(random_email(), random_password(12))
submit_form($url, env("API_KEY"))
```

#### Function capabilities and limits

- `func` supports positional parameters only.
- Functions do not return values; they run commands for side effects.
- Nested function definitions are not supported.
- Calling with the wrong argument count fails with a clear line-numbered error.
- `bdr check your-script.bdr` validates function signatures across files loaded by `exec(...)`.

#### Crafting functions (step-by-step)

Use this pattern when writing reusable flows:

1. Create a focused function name that describes one workflow step.
2. Add all dynamic inputs as `$params`.
3. Use those params directly in element actions and commands.
4. Keep the body to one responsibility (login, search, checkout step).
5. Put shared functions in a separate file and `exec(...)` it before calls.
6. Run `bdr check` to validate function signatures before browser execution.

Copy/paste starter:

```
// shared/actions.bdr
func do_action($input1, $input2) {
  #first-field.fill($input1)
  #second-field.fill($input2)
  #submit.click()
}

// test.bdr
exec("./shared/actions.bdr")
do_action("value one", "value two")
```

```
// shared/auth.bdr
func login($email, $password) {
  #email.fill($email)
  #password.fill($password)
  #submit.click()
}
```

```
// smoke.bdr
exec("./shared/auth.bdr")
load("https://example.com/login")
login(env("EMAIL"), env("PASSWORD"))
```

#### Local scope

Parameters are local to the function — they do not affect variables in the calling script. Variables set inside a function body are also local.

```
$user = "alice"

func greet($name) {
  log("Hello,", $name)
  $user = "overridden"    // only changes the local copy
}

greet("bob")
log($user)                // still prints "alice"
```

Settings (`timeout`, `slow`) are **not** scoped — changing them inside a function affects the rest of the session.

#### Sharing functions across scripts

Define functions in a shared file and `exec` it before calling them:

```
// shared/helpers.bdr
func login($user, $pass) {
  #email.fill($user)
  #password.fill($pass)
  #submit.click()
}

func logout() {
  #user-menu.click()
  .logout-btn.click()
}
```

```
// test.bdr
exec("./shared/helpers.bdr")

load("https://example.com")
login(env("EMAIL"), env("PASSWORD"))
// ... test steps ...
logout()
```

#### Full example — parameterized sign-up flow

```
// multi-user.bdr
timeout = 15000

func sign_up($email, $pass) {
  load("https://example.com/signup")
  #email.fill($email)
  #password.fill($pass)
  #confirm.fill($pass)
  #signup-btn.click()
  #dashboard.wait()
  log("Signed up as", $email)
  screenshot("signed-up.png")
}

func sign_in($email, $pass) {
  load("https://example.com/login")
  #email.fill($email)
  #password.fill($pass)
  #login-btn.click()
  #dashboard.wait()
}

// create two accounts with random credentials
sign_up(random_email(), random_password(12))
sign_up(random_email(), random_password(12))

// sign in as a specific user
sign_in("alice@example.com", "secret123")
log("Done")
```

---

### Screenshots

By default all screenshots go to `~/.bdr/screenshots/`.

```
screenshot("result.png")             # → ~/.bdr/screenshots/result.png
screenshot("step1/login.png")        # → ~/.bdr/screenshots/step1/login.png
```

Change the directory mid-script with `screenshot_dir()`:

```
screenshot_dir("./screenshots")      # relative to CWD where bdr was run
screenshot_dir("./runs/2024-01-15")
screenshot_dir("/tmp/debug")
```

Or set it at the CLI level:

```bash
bdr run script.bdr --screenshot-dir ./screenshots
```

---

### Output

```
log("Reached checkout")
log("Testing as", $user)    # variables expand to their values
```

`log` joins all arguments with a space and prints to the terminal.

---

## Random data

Any argument that accepts a string also accepts a `random_*()` call. The value is generated fresh each time the script runs.

```
// store in a variable
$email = random_email()
$pass  = random_password(16)

// use inline, directly in a chain
#email.fill(random_email())
#password.fill(random_password(16))
#phone.fill(random_phone())
```

---

### Identity

| Call | Example output |
|---|---|
| `random_name()` | `Emma Davis` |
| `random_first_name()` | `Emma` |
| `random_last_name()` | `Davis` |
| `random_username()` | `cnfyoqni` |
| `random_username(12)` | `ja915c1rbpaf` |
| `random_email()` | `p2pbck@demo.app` |
| `random_company()` | `Orbit Software` |

---

### Passwords and strings

| Call | Example output | Notes |
|---|---|---|
| `random_password()` | `MkMA&n8!L9` | 12 chars, mixed case + digits + symbols |
| `random_password(20)` | `#Lzi6UBFdy#!4r%&9^%O` | custom length |
| `random_string()` | `EeCDNYaL1ydr` | 12 chars, letters + digits |
| `random_string(8)` | `63InZEQc` | custom length |
| `random_alpha(10)` | `DHUKmUUTAE` | letters only |
| `random_digits(6)` | `707858` | digits only — PIN codes, verification codes |
| `random_hex(16)` | `97f4a83451690d9d` | hex chars 0-9a-f — tokens, hashes |
| `random_uuid()` | `1ff62b67-11b7-47a1-b2bd-edbf22a3508f` | UUID v4 |

`random_password()` always contains at least one uppercase letter, one digit, and one symbol.

---

### Numbers

| Call | Example output |
|---|---|
| `random_number()` | `3470` — 0 to 9999 |
| `random_number(100)` | `64` — 0 to max |
| `random_number(50, 99)` | `66` — min to max |

---

### Phone numbers

| Call | Example output |
|---|---|
| `random_phone()` | `212-257-3054` |
| `random_phone_intl()` | `+1 697-822-9805` |

---

### Addresses

| Call | Example output |
|---|---|
| `random_address()` | `4005 Washington Avenue` |
| `random_city()` | `Bedford` |
| `random_state()` | `Ohio` |
| `random_state_abbr()` | `CO` |
| `random_zip()` | `69033` |
| `random_country()` | `Netherlands` |

---

### Dates

| Call | Example output | Format |
|---|---|---|
| `random_date()` | `2016-10-15` | `YYYY-MM-DD` — random from last 10 years |
| `random_date_past()` | `05/07/2013` | `MM/DD/YYYY` — random from last 20 years |
| `random_date_future()` | `07/24/2026` | `MM/DD/YYYY` — random up to 5 years out |
| `random_card_expiry()` | `06/29` | `MM/YY` — always in the future |

---

### Payment

| Call | Example output | Notes |
|---|---|---|
| `random_credit_card()` | `4580481246958542` | Luhn-valid 16-digit Visa-format number |
| `random_cvv()` | `970` | 3-digit security code |

These are structurally valid numbers suitable for test environments that validate card format but do not charge real money.

---

### Web and network

| Call | Example output |
|---|---|
| `random_url()` | `https://sandbox-bth1.example.com` |
| `random_ip()` | `81.131.71.53` |
| `random_color()` | `#fe4585` |

---

### Text

| Call | Example output |
|---|---|
| `random_word()` | `prism` |
| `random_sentence()` | `The quick fox jumps over the lazy dog.` |

---

### Full signup form example

```
// signup.bdr
load("https://example.com/signup")

/* generate a complete fake identity */
$name  = random_name()
$email = random_email()
$pass  = random_password(16)
$phone = random_phone()

#full-name.fill($name)
#email.fill($email)
#password.fill($pass)
#confirm-password.fill($pass)
#phone.fill($phone)
#address.fill(random_address())
#city.fill(random_city())
#state.fill(random_state())
#zip.fill(random_zip())
#country.fill(random_country())
#dob.fill(random_date_past())

#submit.click()
#welcome-banner.wait()
log("Signed up as", $name, "—", $email)
screenshot("signup-done.png")
```

---

### Checkout form example

```
// checkout.bdr
load("https://example.com/checkout")

#card-number.fill(random_credit_card())
#card-expiry.fill(random_card_expiry())
#card-cvv.fill(random_cvv())
#card-name.fill(random_name())

#billing-address.fill(random_address())
#billing-city.fill(random_city())
#billing-state.fill(random_state_abbr())
#billing-zip.fill(random_zip())

#place-order.click()
#order-confirmation.wait()
screenshot("checkout-done.png")
```

---

## Worked examples

### Login flow

```
# login.bdr
$url = "https://example.com/login"

load($url)
#email.fill("me@example.com")
#password.fill("hunter2")
#submit.click()
#dashboard.wait()
assert_title("Dashboard")
screenshot("login-done.png")
```

### Multi-step suite

```
# suite.bdr
timeout = 15000

exec("./login.bdr")
exec("./checkout.bdr")

log("All tests passed")
```

### Reusable functions

```
// examples/functions.bdr
exec("./helpers.bdr")
load("https://example.com/login")
login("me@example.com", "hunter2")
search_and_assert("playwright", "Playwright")
```

### Working with lists

```
# Click the second item in a menu
.menu-item[1].click()

# Assert there are exactly 5 results
.result-card.assert_count(5)

# Check the third result's text
.result-card[2].assert_text("Expected title")
```

### Env vars from a .env file

```
# Place a .env file next to your script:
#   EMAIL=me@example.com
#   PASSWORD=hunter2

load("https://example.com/login")
#email.fill(env("EMAIL"))
#password.fill(env("PASSWORD"))
#submit.click()
```

---

## Live status file

bdr writes a live JSON status file while a script runs. It records the process ID, script name, start time, and every action completed so far. The file is deleted automatically when the run finishes — whether it succeeds or fails.

This is designed for LLM agents and CI tools that need to observe a running test.

**Default location:** `~/.bdr/status.json`

**Example contents mid-run:**

```json
{
  "pid": 12345,
  "script": "login.bdr",
  "started": "2026-03-06T10:30:00-05:00",
  "status": "running",
  "actions": [
    {"time": "2026-03-06T10:30:01-05:00", "line": 4, "action": "load(\"https://example.com\")"},
    {"time": "2026-03-06T10:30:02-05:00", "line": 5, "action": "#email.fill(\"me@example.com\")"}
  ]
}
```

If the status file exists, a test is in flight. If it is absent, no test is running (or it completed normally).

### Killing a stuck run

If an agent reads the status file and determines the test is stuck, it can kill the process:

```bash
bdr kill           # sends SIGTERM to the running bdr process
bdr kill --force   # sends SIGKILL if SIGTERM is not enough
```

`bdr kill` reads the PID from the status file, terminates the process, and removes the file.

### Opt out

Status tracking is on by default. Opt out in a script:

```
no_status = true
```

Or from the CLI:

```bash
bdr run script.bdr --no-status
```

### Change the status file path

In a script:

```
status_file("./runs/my-run.json")
```

From the CLI:

```bash
bdr run script.bdr --status-file ./runs/my-run.json
```

---

## Organizing a project

```
my-project/
├── suite.bdr                    ← top-level entry point
├── tests/
│   ├── login.bdr
│   ├── checkout.bdr
│   └── smoke.bdr
└── steps/
    ├── sign-in.bdr              ← reusable login flow
    └── teardown.bdr
```

---

## CLI reference

### `bdr run`

Execute a `.bdr` script.

```bash
bdr run script.bdr
bdr run script.bdr --browser firefox             # chromium (default), firefox, webkit
bdr run script.bdr --headless                    # hide the browser window
bdr run script.bdr --slow 0.5                   # pause 0.5s between commands
bdr run script.bdr --timeout 10000              # element wait timeout in ms (default: 30000)
bdr run script.bdr --screenshot-dir ./ss        # where to save screenshots
bdr run script.bdr --no-status                  # disable the live status file
bdr run script.bdr --status-file ./run.json     # custom status file path
```

### `bdr check`

Validate a script (and every script it `exec`s) without launching a browser.

```bash
bdr check script.bdr
bdr check suite.bdr      # follows all exec() chains recursively
```

Exits `0` if valid, `1` if errors are found.

### `bdr new`

Create a new script from a starter template.

```bash
bdr new my-script.bdr
```

### `bdr seed`

Plant (or refresh) an LLM-oriented seed file in the current project.

The seed embeds the CLI version that generated it. If an existing seed version
does not match the running CLI version, `bdr seed` replaces it and logs the
version transition.

```bash
bdr seed
bdr seed --path AGENT_SEED.md
bdr seed --force
```

### `bdr extract`

Inspect a live page and list stable CSS selectors for its elements — useful for discovering selectors before writing a script.

```bash
bdr extract https://example.com/login "#login-form"
bdr extract https://example.com/login "#login-form" -o selectors/login.el
bdr extract https://example.com "form"  --browser firefox
```

### `bdr screenshots`

List captured screenshots or open the folder.

```bash
bdr screenshots                      # list from the default folder (~/.bdr/screenshots)
bdr screenshots --dir ./shots        # list from a custom folder
bdr screenshots --open               # open the folder in Finder / Explorer
```

### `bdr kill`

Kill any currently running bdr test. Reads the live status file to find the PID and terminates it.

```bash
bdr kill                             # sends SIGTERM
bdr kill --force                     # sends SIGKILL
bdr kill --status-file ./my-run.json # custom status file location
```

### `bdr setup`

Install Playwright browser binaries. Run once after installing bdr or after upgrading Playwright.

```bash
bdr setup                   # installs Chromium (default)
bdr setup --all-browsers    # installs Chromium, Firefox, and WebKit
```

### `bdr --version`

```bash
bdr --version
```

---

## Makefile targets

| Target | Description |
|---|---|
| `make help` | List all targets |
| `make dev` | Set up local dev environment (`uv sync` + `bdr setup`) |
| `make test` | Run the test suite |
| `make install` | Install `bdr` globally via uv tool |
| `make uninstall` | Remove the globally installed `bdr` |
| `make upgrade` | Upgrade the globally installed `bdr` in-place |
| `make build` | Build wheel + sdist for PyPI |
| `make bundle` | Build a self-contained single-file binary |
| `make clean` | Remove build artifacts and caches |

---

## Browser support

| Browser | Flag |
|---|---|
| Chromium | `--browser chromium` (default) |
| Firefox | `--browser firefox` |
| WebKit (Safari) | `--browser webkit` |

```bash
bdr setup --all-browsers    # install all three
bdr run script.bdr --browser webkit
```
