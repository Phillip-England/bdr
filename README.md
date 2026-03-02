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

Settings use bare `name = value` syntax — **no `$` prefix**. The only supported setting is `timeout`.

#### `timeout`

How long bdr waits for elements to appear before failing, in milliseconds.

```
timeout = 10000    # 10 seconds
timeout = 5000     # tighter, faster failures
```

Default is `30000` ms. Can be changed at any point in a script. The `--timeout` CLI flag sets the initial value.

---

### Navigation

```
load("https://example.com")
load("localhost:3000")          # http:// is added automatically
load($url)                      # works with variables

back()
forward()
refresh()
```

---

### Element chains — interaction

```
#submit.click()
.btn-primary.click()
[type="submit"].click()

#email.fill("me@example.com")          # clears then fills
.search-input.fill($query)             # works with variables

#search.type("playwright")             # types character by character

#country.select("United States")       # pick a <select> option by label

[name="agree"].check()                 # check a checkbox
[name="agree"].uncheck()               # uncheck a checkbox

#tooltip-target.hover()
#first-field.focus()

.cta-button.scroll_to()                # scroll element into view
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
bdr run script.bdr --browser firefox      # chromium (default), firefox, webkit
bdr run script.bdr --headless             # hide the browser window
bdr run script.bdr --slow 0.5            # pause 0.5s between commands
bdr run script.bdr --timeout 10000       # element wait timeout in ms (default: 30000)
bdr run script.bdr --screenshot-dir ./ss # where to save screenshots
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
