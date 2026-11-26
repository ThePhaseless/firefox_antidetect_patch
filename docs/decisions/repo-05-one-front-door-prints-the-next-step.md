# repo-05: one front door, and it prints the next step

**Rule.** `python tools/engine.py` with no argument (and `--help`) shows the state of the working tree against the series and the next command to run. Every command that stops prints `next: <the exact command>`.
- A step that a person did by hand because no command did it becomes a command: after a port, `port` writes `mozilla_tag` and `source_branch` in `UPSTREAM.json`; nobody edits them.
- No document step says "edit this file" for a file a command can write.

**Enforced by.** `tools/tests/test_front_door.py`: for each command, every stop path prints a `next:` line whose command exists; the bare command prints the state and the next command; no step in `docs/` is a hand edit of a file a command writes. `port` writes `UPSTREAM.json` (there is no hand edit to test for).

**Why.** In the measurement of the repository, `engine.py --help` was the front door in practice: agents did not open the entry documents first. The one hand edit of `UPSTREAM.json` after a port lived only in `docs/UPDATE.md`, so an agent that skipped that file left the series half moved.

**Files.** `tools/engine.py` (the bare command, `port`, every stop), `tools/tests/test_front_door.py`, [UPDATE.md](../UPDATE.md).

**Don't.**
- Stop with a message that has no `next:` line.
- Write a doc step that edits by hand a file a command can write: add the command.
- Point `next:` at a command that does not exist.
