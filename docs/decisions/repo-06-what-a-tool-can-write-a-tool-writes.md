# repo-06: what a tool can write, a tool writes

**Rule.** A derived fact is written by a tool and never by hand:
- the inventory counts (added, removed, hunks) of each (file, folder) record, the record a new (file, folder) needs (counts, category of the file, feature of the folder, `hookable` where every line is a hook form; anchor and notes stay empty for a hand), and the budget entry of a new (file, folder): `export` writes them, the budget at the counted value (only a raise above main needs a row, [hook-03](hook-03-budgets-and-debt-only-go-down.md));
- the `MANIFEST.json` sha256 of every file `export` writes;
- `layout.OWN_FILES`, derived from each folder's `src/` tree;
- the gtest suites in `tools/gtest-suites.json`, written by `python tools/engine.py gtest-list --write` and read by every consumer;
- the ledger `tag`, derived from `UPSTREAM.json`.

**Enforced by.** `export` writes the counts, the new file's budget and the MANIFEST hashes; `check` refuses a hand-written derived value that differs from what the tool computes, and the failure names the command that rewrites it ([repo-04](repo-04-every-failure-says-where-what-fix-rule.md)). `tools/gtest-suites.json` equals the output of `gtest-list`.

**Why.** In the measurement of a new hook, one change touched about 16 places, 7 of them by hand although a tool could write them; one real commit touched 19 files, 6 of them only for a gtest name. Each hand-written value is a place that drifts.

**Files.** `tools/engine.py` (`export`, `check`, `gtest-list`), `tools/layout.py`, `tools/inventory.json`, `tools/hook-budget.json`, `tools/gtest-suites.json`, `tools/birth-ledger.json`.

**Don't.**
- Type a count, a hash, a suite name or a tag that a command writes.
- Silence `check` by editing a derived value to match: run the command it names.
- Keep a second list of the gtest suites beside `tools/gtest-suites.json`.
