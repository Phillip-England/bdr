"""bdr extractor — scrapes CSS selectors from a live page into a .el file."""

from __future__ import annotations

import pathlib
import re
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page

# ---------------------------------------------------------------------------
# JavaScript injected into the page to collect element data.
#
# Strategy: only emit elements where we can produce a *stable, unique* selector:
#   1. Elements with an `id`            → #id
#   2. Form fields with a `name`        → [name='value']
#   3. <a> tags with a meaningful href  → a[href='value']
#
# Attribute selectors use single quotes so the .el file can wrap them in
# double quotes without any escaping.
# ---------------------------------------------------------------------------

_EXTRACT_JS = """
(rootSelector) => {
    const root = document.querySelector(rootSelector);
    if (!root) return { error: 'selector matched no elements', elements: [] };

    const seen = new Set();
    const elements = [];

    const process = (el) => {
        const tag  = el.tagName.toLowerCase();
        const id   = el.id || null;
        const name = el.getAttribute('name');
        const type = el.getAttribute('type') || null;
        const placeholder = el.getAttribute('placeholder') || null;
        const ariaLabel   = el.getAttribute('aria-label') || null;
        const href = (tag === 'a') ? el.getAttribute('href') : null;
        const text = (el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 60);

        let selector = null;

        if (id) {
            selector = '#' + id;
        } else if (name) {
            // Single quotes inside so the .el file can wrap in double quotes safely.
            selector = "[name='" + name.replace(/'/g, "\\'") + "']";
        } else if (tag === 'a' && href && href.length > 1 && !href.startsWith('javascript')) {
            selector = "a[href='" + href.replace(/'/g, "\\'") + "']";
        }

        if (!selector || seen.has(selector)) return;
        seen.add(selector);

        elements.push({ tag, id, name, type, placeholder, ariaLabel, href, text, selector });
    };

    // Include the root itself, then all descendants.
    process(root);
    root.querySelectorAll('*').forEach(process);

    return { error: null, elements };
}
"""

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_elements(
    page: "Page",
    root_selector: str,
    output: pathlib.Path,
) -> int:
    """Navigate-to-URL is the caller's job. This function:
      1. Evaluates the extraction JS against root_selector.
      2. Assigns human-readable variable names.
      3. Writes the .el file.
    Returns the number of selectors written.
    """
    result = page.evaluate(_EXTRACT_JS, root_selector)

    if result.get("error"):
        raise ValueError(result["error"])

    elements = result.get("elements", [])
    if not elements:
        raise ValueError(f"No extractable elements found under '{root_selector}'")

    seen_names: set[str] = set()
    entries: list[dict] = []
    for el in elements:
        var_name = _make_var_name(el, seen_names)
        if var_name:
            seen_names.add(var_name)
            entries.append({**el, "var_name": var_name})

    _write_el_file(output, page.url, root_selector, entries)
    return len(entries)


# ---------------------------------------------------------------------------
# Variable name generation
# ---------------------------------------------------------------------------

def _make_var_name(el: dict, seen: set[str]) -> str:
    """Derive a clean, unique snake_case variable name from element attributes."""
    tag = el.get("tag", "el")

    # Ordered list of candidates — first non-empty slug wins.
    candidates: list[str] = []
    if el.get("id"):
        candidates.append(el["id"])
    if el.get("name"):
        candidates.append(el["name"])
    if el.get("ariaLabel"):
        candidates.append(el["ariaLabel"])
    if el.get("placeholder"):
        candidates.append(el["placeholder"])
    if el.get("text") and tag in ("button", "a", "label", "h1", "h2", "h3", "option"):
        candidates.append(el["text"])
    if not candidates:
        candidates.append(tag)

    for raw in candidates:
        base = _slugify(str(raw))
        if not base:
            continue
        name = base
        n = 2
        while name in seen:
            name = f"{base}_{n}"
            n += 1
        return name

    return ""


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
    s = re.sub(r"^[0-9_]+", "", s)   # strip leading digits/underscores
    s = re.sub(r"_+", "_", s)
    return s[:40]


# ---------------------------------------------------------------------------
# .el file generation
# ---------------------------------------------------------------------------

# Sort order for grouping elements by type.
_GROUP_ORDER = {"input": 0, "textarea": 1, "select": 2, "button": 3, "a": 4, "form": 5}
_GROUP_LABELS = {0: "inputs", 1: "inputs", 2: "selects", 3: "buttons", 4: "links", 5: "forms", 6: "other"}


def _group_key(el: dict) -> int:
    return _GROUP_ORDER.get(el.get("tag", ""), 6)


def _inline_comment(el: dict) -> str:
    parts = [el.get("tag", "")]
    if el.get("type"):
        parts.append(f"type={el['type']}")
    if el.get("placeholder"):
        parts.append(f'placeholder="{el["placeholder"][:30]}"')
    elif el.get("text") and el.get("tag") not in ("input", "select", "textarea"):
        txt = el["text"][:40].replace('"', "'")
        if txt:
            parts.append(f'"{txt}"')
    return "  # " + " | ".join(p for p in parts if p)


def _write_el_file(
    output: pathlib.Path,
    url: str,
    root_selector: str,
    entries: list[dict],
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines: list[str] = [
        f"# {output.name}",
        f"# Source:  {url}",
        f"# Root:    {root_selector}",
        f"# Created: {now}",
        "#",
        f'# Load in a .bdr script:  load("{output.name}")',
        f"# Reference as variables:  $variable_name",
        "#",
        "",
    ]

    sorted_entries = sorted(entries, key=_group_key)
    current_group: str | None = None

    for entry in sorted_entries:
        group = _GROUP_LABELS.get(_group_key(entry), "other")
        if group != current_group:
            if current_group is not None:
                lines.append("")
            lines.append(f"# --- {group} ---")
            current_group = group

        comment = _inline_comment(entry)
        lines.append(f'{entry["var_name"]} = "{entry["selector"]}"{comment}')

    lines.append("")
    output.write_text("\n".join(lines), encoding="utf-8")
