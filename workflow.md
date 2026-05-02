# Workflow details — NPLAN to Tests

## Step 1 — Fetch the test plan from Confluence

Copy the Confluence page URL and run:

```
python tool/fetch_test_plan.py <confluence_url> --nplan NPLAN-XXXX
```

Real example (NPLAN-6711):

```
python tool/fetch_test_plan.py https://netskope.atlassian.net/wiki/spaces/CDTBA/pages/7875198997 --nplan NPLAN-6711
```

Produces:

```
test_plans/nplan-6711.md      ← structured Markdown with all test cases
test_plans/nplan-6711.html    ← raw Confluence HTML (only with --save-html, for debugging)
```

The output filename is always `test_plans/<nplan-id>.md` (e.g. `nplan-6711.md`).
The Confluence API token is injected automatically from the secrets store — no manual steps needed.

To also save the raw HTML for parser debugging:

```
python tool/fetch_test_plan.py <url> --nplan NPLAN-6711 --save-html
```

To write to a custom path:

```
python tool/fetch_test_plan.py <url> --nplan NPLAN-6711 --output test_plans/my_name.md
```

### What gets extracted

- Only rows that have an explicit ID in the Confluence table are kept — no invented IDs
- Test case title = first paragraph of the description cell
- Steps = bullet list items from the description cell
- Priority, Platform normalised automatically (`P0/P1/P2`, `Windows`, `macOS`, `Linux`, `All`)
- Section text (Feature Description, Scope, etc.) included above the test cases

---

## Step 2 — Scaffold pytest from the Markdown

```
python tool/gen_test_suite.py test_plans/nplan-6711.md
```

Produces:

```
features/nplan_6711_<slug>/
    conftest.py          ← feature-specific fixture stubs
    test_<slug>.py       ← one test_ function per test case
```

Preview without writing files:

```
python tool/gen_test_suite.py test_plans/nplan-6711.md --dry-run
```

Write to a custom folder:

```
python tool/gen_test_suite.py test_plans/nplan-6711.md --output features/nplan_6711_auto_reenable
```

Each test function gets:

- Correct markers (`@pytest.mark.priority_high`, `@pytest.mark.windows`, `@pytest.mark.automated`, etc.)
- Docstring with the full steps and expected result from the test plan
- `raise NotImplementedError  # TODO: implement` for automatable tests
- `pytest.skip("Manual test")` for manual tests

---

## Step 3 — Implement the tests

### Option A — `/gen-test` skill (recommended, requires Claude Code)

The `/gen-test` skill generates **fully implemented** test functions — not just scaffolds.
It reads the test plan, analyses shared patterns, creates fixtures and reusable helpers,
and writes real test logic using the `util_*` toolkit.

```
/gen-test test_plans/nplan-6711.md A01 A02 A03
/gen-test test_plans/nplan-6711.md all
/gen-test test_plans/nplan-6711.md            # lists TCs and asks which to generate
```

The skill lives at `.claude/skills/gen-test/SKILL.md` and ships with the repo — anyone who
clones it gets `/gen-test` automatically (requires a one-time Claude Code restart if the
`.claude/skills/` directory was just created).

### Option B — Manual implementation

Open the generated `test_<slug>.py` and replace each `raise NotImplementedError` with real
test logic using the toolkit APIs (`util_service`, `util_nsclient`, `util_process`, etc.).

---

## Step 4 — Run the tests

```
python -m pytest features/nplan_6711_<slug>/ -v
```

Filter by marker:

```
python -m pytest features/ -m p0                      # P0 only
python -m pytest features/ -m p1                      # P1 only
python -m pytest features/ -m "p0 and windows"        # P0 Windows only
python -m pytest features/ -m "windows and automated" # Windows automatable only
python -m pytest features/ -m "not manual"            # skip manual tests
```

---

## Full example — scaffold workflow

```
# 1. Fetch
python tool/fetch_test_plan.py ^
    https://netskope.atlassian.net/wiki/spaces/CDTBA/pages/7875198997 ^
    --nplan NPLAN-6711

# 2. Scaffold
python tool/gen_test_suite.py test_plans/nplan-6711.md

# 3. Check what was created
python -m pytest features/nplan_6711_wip_nplan_6711_auto_re_enable/ --co -q

# 4. Run P0 tests only
python -m pytest features/nplan_6711_wip_nplan_6711_auto_re_enable/ -m priority_high -v
```
