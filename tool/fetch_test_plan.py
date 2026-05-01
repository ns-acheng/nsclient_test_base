"""
Fetch a Confluence test plan page and convert it to Markdown.

Usage:
    python tool/fetch_test_plan.py <confluence_url> [--nplan NPLAN-XXXX]
    python tool/fetch_test_plan.py <confluence_url> --output test_plans/my_plan.md

The tool:
  1. Extracts the page ID from the Confluence URL
  2. Fetches the page title + body via Confluence REST API
  3. Parses the HTML body (tables → test cases, headings → sections)
  4. Writes structured Markdown to test_plans/<nplan>_<slug>.md

Requires confluence credentials:
  - base_url, username : data/config.json
  - api_token          : encrypted secrets store (python tool/manage_secrets.py set confluence_api_token)
"""

import argparse
import logging
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Tag

# Allow running from project root: python tool/fetch_test_plan.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from util_config import load_config
from util_log import setup_logging

log = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "test_plans"


# ── URL parsing ──────────────────────────────────────────────────────────────

def extract_page_id(url: str) -> str:
    """
    Extract the Confluence page ID from various URL formats.

    Supported formats:
      .../pages/123456/Page+Title
      .../pages/123456
      ...?pageId=123456
      .../display/SPACE/Page+Title  (needs API lookup — not supported here)
    """
    # /pages/<id> pattern
    m = re.search(r"/pages/(\d+)", url)
    if m:
        return m.group(1)

    # ?pageId=<id> query param
    m = re.search(r"[?&]pageId=(\d+)", url)
    if m:
        return m.group(1)

    # Bare numeric ID passed directly
    if url.strip().isdigit():
        return url.strip()

    raise ValueError(
        f"Cannot extract page ID from URL: {url}\n"
        "Expected format: .../pages/123456/... or ?pageId=123456"
    )


# ── Confluence API ───────────────────────────────────────────────────────────

def fetch_page(base_url: str, page_id: str, username: str, api_token: str) -> dict:
    """
    Fetch page title + body.storage from Confluence REST API.

    Returns dict with keys: 'id', 'title', 'body_html', 'url'.
    """
    api_url = f"{base_url.rstrip('/')}/rest/api/content/{page_id}"
    params = {"expand": "body.storage,space"}

    log.info("Fetching page %s from %s", page_id, api_url)
    resp = requests.get(api_url, params=params, auth=(username, api_token), timeout=30)
    resp.raise_for_status()

    data = resp.json()
    space_key = data.get("space", {}).get("key", "")
    return {
        "id": data["id"],
        "title": data["title"],
        "body_html": data["body"]["storage"]["value"],
        "url": f"{base_url.rstrip('/')}/spaces/{space_key}/pages/{page_id}",
    }


# ── HTML → structured data ──────────────────────────────────────────────────

def parse_test_plan_html(html: str) -> dict:
    """
    Parse Confluence HTML body into structured test plan data.

    Returns:
        {
            "sections": [{"heading": str, "content": str}, ...],
            "test_cases": [
                {
                    "id": "TC-001",
                    "title": str,
                    "priority": str,
                    "platform": str,
                    "automatable": str,
                    "preconditions": str,
                    "steps": [str, ...],
                    "expected_result": str,
                },
                ...
            ],
            "raw_text": str,
        }
    """
    soup = BeautifulSoup(html, "html.parser")

    sections = _extract_sections(soup)
    test_cases = _extract_test_cases_from_tables(soup)

    # If no tables found, try to extract from numbered lists
    if not test_cases:
        test_cases = _extract_test_cases_from_lists(soup)

    raw_text = soup.get_text(separator="\n", strip=True)

    return {
        "sections": sections,
        "test_cases": test_cases,
        "raw_text": raw_text,
    }


def _extract_sections(soup: BeautifulSoup) -> list[dict]:
    """
    Extract heading + content pairs from the HTML.

    Skips:
    - Sections whose first meaningful child is a table (rendered as garbage blobs).
    - Empty sections.
    Renders <ul>/<ol> lists as bullet lines instead of squashed text.
    """
    sections = []
    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        content_parts = []
        for sibling in heading.next_siblings:
            if not isinstance(sibling, Tag):
                continue
            if sibling.name and re.match(r"^h[1-6]$", sibling.name):
                break

            # Skip tables entirely in section content — they produce garbage blobs
            if sibling.name == "table":
                content_parts = []   # discard — whole section is table-driven
                break

            if sibling.name in ("ul", "ol"):
                for li in sibling.find_all("li", recursive=False):
                    text = _spaced_text(li).strip()
                    if text:
                        content_parts.append(f"- {text}")
            else:
                text = _spaced_text(sibling).strip()
                if text:
                    content_parts.append(text)

        if content_parts:
            sections.append({
                "heading": heading.get_text(strip=True),
                "content": "\n".join(content_parts),
            })
    return sections


def _extract_test_cases_from_tables(soup: BeautifulSoup) -> list[dict]:
    """
    Extract test cases from HTML tables.

    Pass 1 — scan ALL tables for the Netskope-specific format first
             (Test Types | ID | Priority | Test Description | Platform).
             This avoids early-exit on metadata tables that happen to match
             generic column names.

    Pass 2 — if no Netskope table found, try generic column-mapping on each table.
    """
    all_tables = soup.find_all("table")

    # Pass 1: Netskope format
    for table in all_tables:
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        headers = [_plain_text(c).lower().strip() for c in rows[0].find_all(["th", "td"])]
        if _is_netskope_tc_table(headers):
            tcs = _parse_netskope_tc_table(rows)
            if tcs:
                return tcs

    # Pass 2: generic column mapping
    for table in all_tables:
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        headers = [_plain_text(c).lower().strip() for c in rows[0].find_all(["th", "td"])]
        col_map = _map_columns(headers)
        if col_map:
            tcs = _parse_generic_tc_table(rows, col_map)
            if tcs:
                return tcs

    return []


def _is_netskope_tc_table(headers: list[str]) -> bool:
    """Detect the standard Netskope test plan table: ID + Priority + Test Description."""
    h = set(headers)
    return (
        "id" in h
        and "priority" in h
        and any("description" in hdr for hdr in headers)
    )


def _parse_netskope_tc_table(rows) -> list[dict]:
    """
    Parse a Netskope-style test plan table.

    Column layout (by index):
      0 = Test Types (category, may span multiple rows as empty cells)
      1 = ID         (numeric or empty for sub-rows)
      2 = Priority
      3 = Test Description  — first <p> = title, <ul> items = steps
      4 = Platform
      5 = Status
      6 = Comments

    Rows with no ID and no priority = section label or sub-test; skip unless
    they have a meaningful description (then aggregate as a standalone TC).
    """
    test_cases = []
    current_category = ""

    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        if len(cells) < 4:
            continue

        # Carry the category forward when a cell is non-empty
        cat_text = _plain_text(cells[0]).strip()
        if cat_text:
            current_category = cat_text

        tc_id_raw  = _plain_text(cells[1]).strip()
        priority   = _plain_text(cells[2]).strip()
        desc_cell  = cells[3]
        platform   = _plain_text_multiline(cells[4]).strip() if len(cells) > 4 else ""

        # Skip completely empty rows
        desc_text = _plain_text(desc_cell).strip()
        if not desc_text:
            continue

        # Skip rows that are purely section-label headings (no ID, no priority, short text)
        if not tc_id_raw and not priority and len(desc_text) < 40 and not desc_cell.find("ul"):
            continue

        # Extract title (first <p>) and steps (<ul> items) from the description cell
        title, steps = _split_desc_cell(desc_cell)

        if not title:
            continue

        # Skip rows with no ID in the Confluence table — we never invent IDs
        if not tc_id_raw:
            continue

        # Use the ID exactly as the author wrote it
        tc_id = tc_id_raw

        # Determine automatable from category hint
        automatable = ""
        if current_category.lower() in ("regression",):
            automatable = "Yes"

        test_cases.append({
            "id": tc_id,
            "title": title,
            "priority": _normalise_priority(priority),
            "platform": _normalise_platform(platform),
            "automatable": automatable,
            "preconditions": "",
            "steps": steps,
            "expected_result": "",
        })

    return test_cases


def _split_desc_cell(cell) -> tuple[str, list[str]]:
    """
    Split a Netskope description cell into (title, steps).

    Cell structure:
      <p>[optional highlight label] actual title text</p>
      <ul><li>step 1</li><li>step 2</li></ul>

    Highlight labels are `<strong><span style="background-color:...">Label</span></strong>`
    at the start of the first <p>.  They are category hints (e.g. "Auto Upgrade"), not
    part of the test title — strip them.
    """
    import copy

    paragraphs = cell.find_all("p", recursive=False)
    lists      = cell.find_all("ul", recursive=False)

    # Title = first non-empty paragraph, with highlight labels removed
    title = ""
    for p in paragraphs:
        p_copy = copy.copy(p)
        # Remove leading <strong><span style="background-color...">...</span></strong> labels
        for strong in p_copy.find_all("strong"):
            spans = strong.find_all("span", style=re.compile(r"background-color"))
            if spans:
                strong.decompose()
        t = _spaced_text(p_copy).strip()
        if t:
            title = t
            break

    # Steps = all <li> items across all <ul>s
    steps = []
    for ul in lists:
        for li in ul.find_all("li"):
            step = _spaced_text(li).strip()
            if step:
                steps.append(step)

    # If no explicit steps but multiple paragraphs, treat extra paragraphs as steps
    if not steps and len(paragraphs) > 1:
        for p in paragraphs[1:]:
            t = _spaced_text(p).strip()
            if t:
                steps.append(t)

    return title, steps


def _map_columns(headers: list[str]) -> dict[str, int]:
    """Map known field names to column indices (generic format fallback)."""
    mapping = {}
    keywords = {
        "id":             ["id", "#", "test id", "tc id", "test case id", "no", "no."],
        "title":          ["title", "name", "test case", "test case name", "description", "summary",
                           "test scenario", "scenario", "test description"],
        "priority":       ["priority", "severity"],
        "platform":       ["platform", "os", "target os", "target platform"],
        "automatable":    ["automatable", "automation", "auto", "automated", "automation status"],
        "preconditions":  ["preconditions", "precondition", "prerequisites", "pre-conditions", "setup"],
        "steps":          ["steps", "test steps", "procedure", "action", "actions"],
        "expected_result":["expected", "expected result", "expected results", "result",
                           "expected output", "expected behavior", "expected behaviour", "pass criteria"],
    }

    for field, synonyms in keywords.items():
        for i, header in enumerate(headers):
            if header in synonyms or any(s in header for s in synonyms):
                mapping[field] = i
                break

    if "title" not in mapping and "steps" not in mapping:
        return {}
    return mapping


def _parse_generic_tc_table(rows, col_map: dict[str, int]) -> list[dict]:
    """Parse a generic column-mapped test case table (non-Netskope format)."""
    test_cases = []
    counter = 0

    for row in rows[1:]:
        cells = row.find_all(["td", "th"])

        def _get(field: str) -> str:
            idx = col_map.get(field)
            return _plain_text(cells[idx]) if idx is not None and idx < len(cells) else ""

        title      = _get("title")
        steps_text = _get("steps")
        if not title and not steps_text:
            continue

        counter += 1
        raw_id = _get("id")
        if raw_id.isdigit():
            tc_id = f"TC-{int(raw_id):03d}"
        else:
            tc_id = raw_id or f"TC-{counter:03d}"

        test_cases.append({
            "id": tc_id,
            "title": title,
            "priority": _normalise_priority(_get("priority")),
            "platform": _normalise_platform(_get("platform")),
            "automatable": _normalise_automatable(_get("automatable")),
            "preconditions": _get("preconditions"),
            "steps": _split_steps(steps_text) if steps_text else [],
            "expected_result": _get("expected_result"),
        })

    return test_cases


def _extract_test_cases_from_lists(soup: BeautifulSoup) -> list[dict]:
    """Fallback: extract test cases from numbered/bulleted lists under headings."""
    test_cases = []
    tc_counter = 0

    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        heading_text = heading.get_text(strip=True)
        # Look for headings that seem like test cases
        if not re.search(r"(test\s*case|tc[- ]?\d|scenario)", heading_text, re.IGNORECASE):
            continue

        tc_counter += 1
        steps = []
        expected = ""

        for sibling in heading.next_siblings:
            if isinstance(sibling, Tag):
                if sibling.name and re.match(r"^h[1-6]$", sibling.name):
                    break
                if sibling.name in ("ol", "ul"):
                    for li in sibling.find_all("li"):
                        steps.append(li.get_text(strip=True))
                text = sibling.get_text(strip=True).lower()
                if "expected" in text:
                    expected = sibling.get_text(strip=True)

        test_cases.append({
            "id": f"TC-{tc_counter:03d}",
            "title": heading_text,
            "priority": "",
            "platform": "All",
            "automatable": "",
            "preconditions": "",
            "steps": steps,
            "expected_result": expected,
        })

    return test_cases


# ── Text extraction helpers ──────────────────────────────────────────────────

def _plain_text(element) -> str:
    """Plain collapsed text from any element — no structure preserved."""
    return element.get_text(separator=" ", strip=True)


def _plain_text_multiline(element) -> str:
    """
    Text from a cell that may contain multiple <p> blocks (e.g. platform = 'Windows\nMac').
    Joins all <p> text with ' / '.
    """
    parts = [p.get_text(strip=True) for p in element.find_all("p")]
    if parts:
        return " / ".join(p for p in parts if p)
    return element.get_text(separator=" ", strip=True)


def _spaced_text(element) -> str:
    """
    Extract text from an element, injecting a space before inline tags so that
    '<p>Set<strong>Auto</strong>duration</p>' → 'Set Auto duration' (not 'SetAutoduration').
    """
    import copy
    el = copy.copy(element)
    # Insert a space before each inline tag child
    inline_tags = {"strong", "em", "b", "i", "a", "span", "code", "tt"}
    for tag in el.find_all(inline_tags):
        tag.insert_before(" ")
        tag.insert_after(" ")
    text = el.get_text(separator="", strip=False)
    # Collapse multiple spaces
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text


# ── Normalisation helpers ────────────────────────────────────────────────────


def _split_steps(text: str) -> list[str]:
    """Split steps text into individual step strings."""
    # Try numbered steps first: "1. xxx 2. xxx"
    numbered = re.split(r"\n?\d+[.)]\s*", text)
    numbered = [s.strip() for s in numbered if s.strip()]
    if len(numbered) > 1:
        return numbered

    # Try newline-separated
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) > 1:
        return lines

    # Single block — return as-is
    return [text] if text else []


def _normalise_priority(raw: str) -> str:
    """Normalise priority to P0/P1/P2 or pass through."""
    low = raw.lower().strip()
    if not low:
        return ""
    if low in ("p0", "critical", "blocker", "high"):
        return "P0"
    if low in ("p1", "major", "medium"):
        return "P1"
    if low in ("p2", "minor", "low"):
        return "P2"
    return raw.strip()


def _normalise_automatable(raw: str) -> str:
    """Normalise automatable field to Yes/No/Partial."""
    low = raw.lower().strip()
    if not low:
        return ""
    if low in ("yes", "y", "true", "auto", "automated", "full"):
        return "Yes"
    if low in ("no", "n", "false", "manual"):
        return "No"
    if low in ("partial", "semi", "partially"):
        return "Partial"
    return raw.strip()


def _normalise_platform(raw: str) -> str:
    """
    Normalise platform text to a clean comma-separated list.

    'WindowsMac' → 'Windows, macOS'
    'all'        → 'All'
    'Windows / Mac' → 'Windows, macOS'
    """
    if not raw.strip():
        return "All"
    low = raw.lower().strip()
    if low in ("all", "any", "all platforms"):
        return "All"

    # Split on common separators first
    parts = re.split(r"[,/\n]+", raw)
    if len(parts) == 1:
        # Try splitting fused words: 'WindowsMac' → ['Windows', 'Mac']
        parts = re.findall(r"[A-Z][a-z]+(?:[A-Z][a-z]+)*|[a-z]+", raw)

    result = []
    for part in parts:
        p = part.strip()
        if not p:
            continue
        pl = p.lower()
        if pl in ("windows", "win"):
            result.append("Windows")
        elif pl in ("mac", "macos", "darwin", "osx"):
            result.append("macOS")
        elif pl in ("linux",):
            result.append("Linux")
        elif pl in ("all", "any"):
            return "All"
        else:
            result.append(p)

    return ", ".join(result) if result else "All"


# ── Markdown generation ──────────────────────────────────────────────────────

def generate_markdown(page_info: dict, plan_data: dict, nplan: str) -> str:
    """
    Generate structured Markdown from parsed test plan data.

    Args:
        page_info: dict from fetch_page() with id, title, url.
        plan_data: dict from parse_test_plan_html().
        nplan: NPLAN identifier (e.g. "NPLAN-6711").
    """
    title = page_info["title"]
    lines = [f"# {nplan}: {title}", ""]

    # Source section
    lines.append("## Source")
    lines.append(f"- Confluence: [{title}]({page_info['url']})")
    lines.append(f"- Page ID: {page_info['id']}")
    lines.append(f"- Date fetched: {time.strftime('%Y-%m-%d')}")
    lines.append("")

    # Non-test-case sections (requirements, description, etc.)
    if plan_data["sections"]:
        for section in plan_data["sections"]:
            heading = section["heading"]
            # Skip sections that are just table-of-contents or empty
            if not section["content"] or len(section["content"]) < 5:
                continue
            # Skip headings that are clearly test case headers (handled below)
            if re.search(r"^(tc[- ]?\d|test\s*case\s*\d)", heading, re.IGNORECASE):
                continue
            lines.append(f"## {heading}")
            lines.append(section["content"])
            lines.append("")

    # Test cases
    if plan_data["test_cases"]:
        lines.append("## Test Cases")
        lines.append("")

        for tc in plan_data["test_cases"]:
            lines.append(f"### {tc['id']}: {tc['title']}")
            if tc["priority"]:
                lines.append(f"- **Priority**: {tc['priority']}")
            if tc["platform"] and tc["platform"] != "All":
                lines.append(f"- **Platform**: {tc['platform']}")
            if tc["automatable"]:
                lines.append(f"- **Automatable**: {tc['automatable']}")
            if tc["preconditions"]:
                lines.append(f"- **Preconditions**: {tc['preconditions']}")
            if tc["steps"]:
                lines.append("- **Steps**:")
                for i, step in enumerate(tc["steps"], 1):
                    lines.append(f"  {i}. {step}")
            if tc["expected_result"]:
                lines.append(f"- **Expected Result**: {tc['expected_result']}")
            lines.append("")
    else:
        # No structured test cases found — dump raw text
        lines.append("## Raw Content")
        lines.append("")
        lines.append("_No structured test cases extracted. Raw page text below._")
        lines.append("")
        lines.append("```")
        lines.append(plan_data["raw_text"][:5000])
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


# ── File output ──────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_]+", "_", slug).strip("_-")
    return slug[:60]


def write_markdown(md_text: str, output_path: Path) -> Path:
    """Write Markdown to file, creating parent directories."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(md_text, encoding="utf-8")
    log.info("Test plan written: %s", output_path)
    return output_path


# ── CLI ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch a Confluence test plan page and convert to Markdown.",
        epilog="Example: python tool/fetch_test_plan.py https://netskope.atlassian.net/.../pages/123456",
    )
    parser.add_argument("url", help="Confluence page URL or numeric page ID")
    parser.add_argument(
        "--nplan", default="",
        help="NPLAN identifier (e.g. NPLAN-6711). Auto-extracted from title if omitted.",
    )
    parser.add_argument(
        "--output", "-o", default="",
        help="Output .md file path. Default: test_plans/<nplan>.md",
    )
    parser.add_argument(
        "--save-html", action="store_true",
        help="Save raw Confluence HTML alongside the .md for parser debugging.",
    )
    parser.add_argument(
        "--config", default="",
        help="Path to config.json (default: data/config.json)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(verbose=args.verbose)

    # Load config for Confluence credentials
    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)
    conf = config.confluence

    if not conf.username:
        log.error(
            "Confluence username not configured.\n"
            "Set 'confluence.username' in data/config.json"
        )
        return 1

    if not conf.api_token:
        log.error(
            "Confluence API token not found.\n"
            "Run: python tool/manage_secrets.py set confluence_api_token"
        )
        return 1

    # Extract page ID
    try:
        page_id = extract_page_id(args.url)
    except ValueError as exc:
        log.error("%s", exc)
        return 2

    # Fetch page
    try:
        page_info = fetch_page(conf.base_url, page_id, conf.username, conf.api_token)
    except requests.HTTPError as exc:
        log.error("Confluence API error: %s", exc)
        return 1
    except requests.ConnectionError:
        log.error("Cannot connect to Confluence at %s", conf.base_url)
        return 1

    log.info("Page title: %s", page_info["title"])

    # Determine NPLAN identifier
    nplan = args.nplan
    if not nplan:
        m = re.search(r"(NPLAN[- ]?\d+)", page_info["title"], re.IGNORECASE)
        nplan = m.group(1).upper().replace(" ", "-") if m else "NPLAN-UNKNOWN"

    # Determine output path — clean name: test_plans/nplan-6711.md
    if args.output:
        output_path = Path(args.output)
    else:
        filename = f"{nplan.lower()}.md"   # e.g. nplan-6711.md
        output_path = OUTPUT_DIR / filename

    # Save raw HTML if requested (write next to the .md as .html)
    if args.save_html:
        html_path = output_path.with_suffix(".html")
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(page_info["body_html"], encoding="utf-8")
        log.info("Raw HTML saved: %s", html_path)
        print(f"HTML : {html_path}")

    # Parse HTML
    plan_data = parse_test_plan_html(page_info["body_html"])
    tc_count = len(plan_data["test_cases"])
    log.info("Extracted %d test case(s), %d section(s)", tc_count, len(plan_data["sections"]))

    # Generate Markdown
    md_text = generate_markdown(page_info, plan_data, nplan)

    write_markdown(md_text, output_path)
    print(f"MD   : {output_path}  ({tc_count} test cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
