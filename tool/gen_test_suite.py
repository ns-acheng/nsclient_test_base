"""
Scaffold a pytest feature test suite from a test plan Markdown file.

Usage:
    python tool/gen_test_suite.py test_plans/nplan_6711_auto_reenable.md
    python tool/gen_test_suite.py test_plans/nplan_6711_auto_reenable.md --output features/custom_name

The tool:
  1. Reads a test plan Markdown (produced by fetch_test_plan.py)
  2. Parses the NPLAN ID and test cases from Markdown headings/bullets
  3. Creates features/nplan_XXXX/ with:
     - conftest.py  (feature-specific fixtures, placeholder)
     - test_<feature>.py (one test_ function per test case)
"""

import argparse
import logging
import re
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from util_log import setup_logging

log = logging.getLogger(__name__)

FEATURES_DIR = Path(__file__).resolve().parent.parent / "features"


# ── Markdown parsing ─────────────────────────────────────────────────────────

def parse_test_plan_md(md_text: str) -> dict:
    """
    Parse a test plan Markdown file into structured data.

    Returns:
        {
            "nplan": "NPLAN-6711",
            "title": "Feature Name",
            "source_url": "https://...",
            "test_cases": [
                {
                    "id": "TC-001",
                    "title": "Test case title",
                    "priority": "P0",
                    "platform": "All",
                    "automatable": "Yes",
                    "preconditions": "...",
                    "steps": ["step 1", "step 2"],
                    "expected_result": "...",
                },
                ...
            ],
        }
    """
    lines = md_text.splitlines()

    nplan = ""
    title = ""
    source_url = ""
    test_cases = []

    # Parse H1 for NPLAN and title
    for line in lines:
        m = re.match(r"^#\s+(NPLAN[- ]\w+):\s*(.+)", line, re.IGNORECASE)
        if m:
            nplan = m.group(1).upper().replace(" ", "-")
            title = m.group(2).strip()
            break

    if not nplan:
        # Try to find NPLAN anywhere in the first 20 lines
        for line in lines[:20]:
            m = re.search(r"(NPLAN[- ]?\d+)", line, re.IGNORECASE)
            if m:
                nplan = m.group(1).upper().replace(" ", "-")
                break

    # Extract source URL
    for line in lines:
        m = re.search(r"Confluence:\s*\[.*?\]\((https?://[^\)]+)\)", line)
        if m:
            source_url = m.group(1)
            break

    # Parse test cases from ### TC-XXX headings
    current_tc = None
    current_field = None

    for line in lines:
        # New test case heading: ### TC-001: Title
        tc_match = re.match(r"^###\s+(TC[- ]?\d+):\s*(.+)", line, re.IGNORECASE)
        if tc_match:
            if current_tc:
                test_cases.append(current_tc)
            current_tc = {
                "id": tc_match.group(1).upper().replace(" ", "-"),
                "title": tc_match.group(2).strip(),
                "priority": "",
                "platform": "All",
                "automatable": "",
                "preconditions": "",
                "steps": [],
                "expected_result": "",
            }
            current_field = None
            continue

        if current_tc is None:
            continue

        # Field lines: - **Priority**: P0
        field_match = re.match(r"^-\s+\*\*(\w[\w\s]*)\*\*:\s*(.*)", line)
        if field_match:
            field_name = field_match.group(1).lower().strip()
            field_value = field_match.group(2).strip()

            if "priority" in field_name:
                current_tc["priority"] = field_value
                current_field = None
            elif "platform" in field_name:
                current_tc["platform"] = field_value
                current_field = None
            elif "automatable" in field_name or "automation" in field_name:
                current_tc["automatable"] = field_value
                current_field = None
            elif "precondition" in field_name:
                current_tc["preconditions"] = field_value
                current_field = None
            elif "step" in field_name:
                current_field = "steps"
            elif "expected" in field_name:
                current_tc["expected_result"] = field_value
                current_field = "expected_result"
            continue

        # Numbered step lines:   1. Do something
        step_match = re.match(r"^\s+\d+[.)]\s+(.+)", line)
        if step_match and current_field == "steps":
            current_tc["steps"].append(step_match.group(1).strip())
            continue

        # Continuation of expected_result on next line
        if current_field == "expected_result" and line.strip() and not line.startswith("-"):
            current_tc["expected_result"] += " " + line.strip()

    if current_tc:
        test_cases.append(current_tc)

    return {
        "nplan": nplan or "NPLAN-UNKNOWN",
        "title": title,
        "source_url": source_url,
        "test_cases": test_cases,
    }


# ── Code generation ──────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    """Convert to a Python-identifier-safe slug."""
    slug = re.sub(r"[^\w\s]", "", text.lower())
    slug = re.sub(r"\s+", "_", slug).strip("_")
    return slug[:50]


def _tc_to_function_name(tc: dict) -> str:
    """Generate a test function name from a test case."""
    slug = _slugify(tc["title"])
    return f"test_{tc['id'].lower().replace('-', '_')}_{slug}"


def _build_markers(tc: dict) -> list[str]:
    """Build pytest marker decorators for a test case."""
    markers = []

    # Priority markers — long form + short alias so users can filter by either
    priority_map = {
        "P0": ("priority_high", "p0"),
        "P1": ("priority_medium", "p1"),
        "P2": ("priority_low", "p2"),
    }
    if tc["priority"] in priority_map:
        long, short = priority_map[tc["priority"]]
        markers.append(f"@pytest.mark.{long}")
        markers.append(f"@pytest.mark.{short}")

    # Platform marker
    platform = tc.get("platform", "All").lower()
    if platform in ("windows", "win"):
        markers.append("@pytest.mark.windows")
    elif platform in ("macos", "mac", "darwin"):
        markers.append("@pytest.mark.macos")
    elif platform in ("linux",):
        markers.append("@pytest.mark.linux")

    # Automation marker
    auto = tc.get("automatable", "").lower()
    if auto in ("yes", "full"):
        markers.append("@pytest.mark.automated")
    elif auto in ("no", "manual"):
        markers.append("@pytest.mark.manual")

    return markers


def _build_docstring(tc: dict) -> str:
    """Build a docstring for a test function."""
    parts = [tc["title"]]

    if tc["preconditions"]:
        parts.append(f"\nPreconditions:\n    {tc['preconditions']}")

    if tc["steps"]:
        parts.append("\nSteps:")
        for i, step in enumerate(tc["steps"], 1):
            parts.append(f"    {i}. {step}")

    if tc["expected_result"]:
        parts.append(f"\nExpected Result:\n    {tc['expected_result']}")

    return "\n".join(parts)


def generate_test_file(plan_data: dict) -> str:
    """Generate a complete test_*.py file from parsed test plan data."""
    nplan = plan_data["nplan"]
    title = plan_data["title"] or nplan

    lines = [
        f'"""',
        f"Feature tests for {nplan}: {title}",
        f"",
        f"Auto-generated from test plan. Implement each test case body.",
        f'"""',
        f"",
        f"import pytest",
        f"",
    ]

    if not plan_data["test_cases"]:
        lines.append("")
        lines.append("# No test cases extracted from the test plan.")
        lines.append("# Add test functions manually or re-run fetch_test_plan.py.")
        lines.append("")
        return "\n".join(lines)

    for tc in plan_data["test_cases"]:
        func_name = _tc_to_function_name(tc)
        markers = _build_markers(tc)
        docstring = _build_docstring(tc)

        # Add blank line between test functions
        lines.append("")

        # Markers
        for marker in markers:
            lines.append(marker)

        # Function definition
        lines.append(f"def {func_name}():")

        # Docstring
        doc_lines = docstring.splitlines()
        if len(doc_lines) == 1:
            lines.append(f'    """{doc_lines[0]}"""')
        else:
            lines.append(f'    """')
            for dl in doc_lines:
                lines.append(f"    {dl}" if dl else "")
            lines.append(f'    """')

        # Body — skip for manual tests, raise NotImplementedError for automated
        auto = tc.get("automatable", "").lower()
        if auto in ("no", "manual"):
            lines.append(f'    pytest.skip("Manual test — requires human verification")')
        else:
            lines.append(f"    raise NotImplementedError  # TODO: implement")

        lines.append("")

    return "\n".join(lines)


def generate_conftest(plan_data: dict) -> str:
    """Generate a feature-specific conftest.py."""
    nplan = plan_data["nplan"]
    title = plan_data["title"] or nplan

    return textwrap.dedent(f'''\
        """
        Fixtures for {nplan}: {title}

        Add feature-specific fixtures here. Shared fixtures are inherited
        from features/conftest.py (project_config, install_dir, nsconfig, etc.).
        """

        # import pytest
        # from util_service import SVC_CLIENT


        # @pytest.fixture()
        # def feature_precondition():
        #     """Example: set up state needed by this feature's tests."""
        #     pass
    ''')


# ── File output ──────────────────────────────────────────────────────────────

def write_feature_folder(
    plan_data: dict,
    output_dir: Path | None = None,
) -> Path:
    """
    Create the feature test folder with conftest.py and test_*.py.

    Returns the created folder path.
    """
    nplan = plan_data["nplan"]
    title_slug = _slugify(plan_data["title"]) if plan_data["title"] else "feature"

    if output_dir is None:
        folder_name = f"{nplan.lower().replace('-', '_')}_{title_slug}"
        output_dir = FEATURES_DIR / folder_name

    output_dir.mkdir(parents=True, exist_ok=True)

    # Write conftest.py
    conftest_path = output_dir / "conftest.py"
    conftest_path.write_text(generate_conftest(plan_data), encoding="utf-8")
    log.info("Created: %s", conftest_path)

    # Write test file
    test_filename = f"test_{title_slug}.py" if title_slug else "test_feature.py"
    test_path = output_dir / test_filename
    test_path.write_text(generate_test_file(plan_data), encoding="utf-8")
    log.info("Created: %s", test_path)

    return output_dir


# ── CLI ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scaffold pytest feature tests from a test plan Markdown file.",
        epilog="Example: python tool/gen_test_suite.py test_plans/nplan_6711_auto_reenable.md",
    )
    parser.add_argument("markdown", help="Path to the test plan Markdown file")
    parser.add_argument(
        "--output", "-o", default="",
        help="Output folder path. Default: features/<nplan>_<slug>/",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print generated code without writing")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(verbose=args.verbose)

    md_path = Path(args.markdown)
    if not md_path.is_file():
        log.error("Markdown file not found: %s", md_path)
        return 2

    md_text = md_path.read_text(encoding="utf-8")
    plan_data = parse_test_plan_md(md_text)

    tc_count = len(plan_data["test_cases"])
    log.info("Parsed: %s — %s (%d test cases)", plan_data["nplan"], plan_data["title"], tc_count)

    if tc_count == 0:
        log.warning("No test cases found in %s", md_path)

    if args.dry_run:
        print("=== conftest.py ===")
        print(generate_conftest(plan_data))
        print(f"=== test_{_slugify(plan_data['title']) or 'feature'}.py ===")
        print(generate_test_file(plan_data))
        return 0

    output_dir = Path(args.output) if args.output else None
    folder = write_feature_folder(plan_data, output_dir)

    print(f"Done: {folder}  ({tc_count} test cases scaffolded)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
