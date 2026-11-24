# platform/repo

Category: build, other
Prefs: none read directly
Test: tools/tests/test_repo_files_are_ours.py of the series (test_release_out_is_ignored_by_its_own_gitignore, test_claude_md_is_the_tag_plus_one_line_naming_a_file_that_exists, test_readme_md_is_the_tag_plus_one_line_naming_a_file_that_exists)

## What it does

The text this fork adds for readers and agents lives in files of ours, not
inside Mozilla's.

- `STEALTH_README.md`: what is patched and why, the pointer to the patch series
  (STEALTH_BRANCH_README.md), the anonymous launch counter's disclosure (what is
  sent, when, why; the address is a constant of
  browser/components/StealthLaunchCounter.sys.mjs), where to report bugs of the
  fork, and the notice that the project is an unaffiliated fork of Firefox. Moved
  verbatim from README.md.
- `STEALTH_CLAUDE.md`: the instructions for agents working in this tree (the
  workbench, how to build, CI). Moved verbatim from CLAUDE.md; the text is old
  (branch stealth/157, a firefox-150 build mirror) and is not corrected here.
- `release-out/.gitignore` (`*` and `!.gitignore`): git ignores everything the
  release script writes under release-out/, which the root .gitignore used to
  say with one line. The file is tracked so the directory exists.
- `STEALTH_BRANCH_README.md`: the branch's own readme (unchanged).

## Hooks in Mozilla files

- `README.md`: one line at the top that points to STEALTH_README.md (the
  disclosure that this is a modified Firefox, and the launch counter's, must
  stay one click from the README; StealthLaunchCounter.sys.mjs says its full
  disclosure is in the README). Mozilla's three reworded lines (the bugzilla
  sentence and two resource bullets) are as in the tag.
- `CLAUDE.md`: one line, `@STEALTH_CLAUDE.md`, BEFORE Mozilla's `@AGENTS.md`
  (Claude Code expands an `@path` import wherever it stands; the HTML comment
  after the path is outside the import token). It is the first line of a
  two-line file.
- `.gitignore` is as in the tag.

## Our own files

- `STEALTH_BRANCH_README.md`
- `STEALTH_CLAUDE.md`
- `STEALTH_README.md`
- `release-out/.gitignore`
