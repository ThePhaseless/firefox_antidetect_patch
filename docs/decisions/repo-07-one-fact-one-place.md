# repo-07: one fact, one place

**Rule.** Each fact is written once; every other place derives it or cites it, never restates it.
- Hook rules: only the `RULES` table in `tools/hook_contract.py`. `docs/STRUCTURE.md` and [hook-02](hook-02-shape-and-contract.md) carry sections generated from it.
- The Mozilla tag: only `UPSTREAM.json`.
- The gtest suites: only `tools/gtest-suites.json` ([repo-06](repo-06-what-a-tool-can-write-a-tool-writes.md)).
- Ceilings: one budget file per kind of ceiling; a one-off realignment file does not stay.

**Enforced by.** `python tools/engine.py docs --check` fails when a generated section differs from the generator's output (`docs --write` rewrites it). A test fails when the Mozilla tag appears in a file other than `UPSTREAM.json`, or when two budget files carry the same kind of ceiling.

**Why.** In the measurement, the gtest list was in about 5 places, the budgets in four files, the Mozilla tag was typed by hand in two, and the hook rules were written in five places that had already diverged. A reader could not tell which copy was true.

**Files.** `tools/hook_contract.py` (`RULES`), `tools/engine.py` (`docs`), `docs/STRUCTURE.md`, `docs/decisions/hook-02-shape-and-contract.md`, `UPSTREAM.json`, `tools/*budget*.json`.

**Don't.**
- Edit a generated section by hand: change `RULES` and run `docs --write`.
- Copy the tag, a rule or a suite list into a document, script or workflow: read the one place.
- Add a budget file for a ceiling that already has one.
