# repo-08: no unread file, no outside reference

**Rule.** Every file in the repository is read by a workflow, a script, a test or the build, or is a human entry file (`README`, `AGENTS`, `docs/`, `.gitattributes`, `.gitignore`).
- No code, docstring or message points outside the repository.
- Every code a message prints (`C*`, `G*`, `T*`) is explained in the repository: in the `RULES` table of `tools/hook_contract.py` and its explanation table.

**Enforced by.** A test that lists the unread files and the outside references, one line per site as `file:line`, and fails on any; a second check that every printed code has an entry in the `RULES` table and its explanation table.

**Why.** In the measurement, 10 files were read by nothing (a drift checker, a survival script with its data, a test folder, an empty package marker). Docstrings in `hook_contract.py` and `hooks_list.py` pointed to files outside the repository for the explanation of the `G*` codes, so a reader who followed a code reached a dead end.

**Files.** `tools/hook_contract.py`, `tools/hooks_list.py`, the test that lists unread files and outside references, `.github/workflows/`.

**Don't.**
- Keep a file "for later" that no workflow, script, test or build reads: wire it into a check or delete it.
- Write a path outside the repository in code or a docstring: put the explanation here.
- Print a code without an entry that explains it.
