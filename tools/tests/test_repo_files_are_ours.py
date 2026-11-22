"""The tree's CLAUDE.md and README.md are Mozilla's files: ours says nothing inside them.

Each carries exactly one hook line, in front of Mozilla's first line, that points to a file of ours
(STEALTH_CLAUDE.md, STEALTH_README.md); our text lives in that file, which platform/repo owns (MANIFEST
`added`, a file under src/). The checks read the series' platform/repo hooks.patch.

Until the series holds that form (its MANIFEST does not list the two files yet) the checks of the real series
have nothing to judge; the red/green cases on a patch text judge the checker itself.

    python -m pytest tools/tests/test_repo_files_are_ours.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine  # noqa: E402

FOLDER = engine.ROOT / "platform" / "repo"
CLAUDE_HOOK = "@STEALTH_CLAUDE.md <!-- STEALTH-HOOK(platform/repo) -->"
README_HOOK = ("[Notes of this fork, the anonymous launch counter and where to report bugs: STEALTH_README.md]"
               "(STEALTH_README.md) <!-- STEALTH-HOOK(platform/repo) -->")
CLAUDE_FIRST = "@AGENTS.md"
README_FIRST = "![Firefox Browser](./docs/readme/readme-banner.svg)"


def file_section(patch_text, name):
    """The lines of the diff of `name` (from its `diff --git` line to the next one), [] if the patch has none."""
    out, inside = [], False
    for line in patch_text.split("\n"):
        if line.startswith("diff --git "):
            inside = line == "diff --git a/%s b/%s" % (name, name)
        if inside:
            out.append(line)
    return out


def hook_problems(patch_text, manifest, src_files, name, hook, first, target):
    """Why `name` is not 'Mozilla's file plus one hook line to `target`'; [] when it is."""
    section = file_section(patch_text, name)
    if not section:
        return ["%s is not in the patch" % name]
    hunks = [i for i, ln in enumerate(section) if ln.startswith("@@")]
    if len(hunks) != 1:
        return ["%s has %d hunks, one expected" % (name, len(hunks))]
    if not section[hunks[0]].startswith(("@@ -1,", "@@ -1 ")):
        return ["the hunk of %s does not start at line 1: the hook line goes in front of Mozilla's first line" % name]
    body = section[hunks[0] + 1:]
    added = [ln[1:] for ln in body if ln.startswith("+")]
    removed = [ln for ln in body if ln.startswith("-")]
    bad = []
    if removed:
        bad.append("%s removes %d of Mozilla's lines" % (name, len(removed)))
    if [a for a in added if a.strip()] != [hook]:
        bad.append("%s adds more or other than the one hook line: %r" % (name, [a for a in added if a.strip()]))
    if not body or body[0] != "+" + hook:
        bad.append("the hook line is not the first line of %s" % name)
    context = [ln[1:] for ln in body if ln.startswith(" ") and ln[1:].strip()]
    if not context or context[0] != first:
        bad.append("the hook line of %s is not in front of %r" % (name, first))
    if "(%s)" % target not in hook and "@%s" % target not in hook:
        bad.append("the hook line of %s does not name %s" % (name, target))
    if target not in manifest.get("added", {}):
        bad.append("%s is not an own file of platform/repo: not in the MANIFEST `added`" % target)
    if target not in src_files:
        bad.append("%s is not under platform/repo/src" % target)
    return bad


def claude_md_problems(patch_text, manifest, src_files):
    return hook_problems(patch_text, manifest, src_files, "CLAUDE.md", CLAUDE_HOOK, CLAUDE_FIRST, "STEALTH_CLAUDE.md")


def readme_md_problems(patch_text, manifest, src_files):
    return hook_problems(patch_text, manifest, src_files, "README.md", README_HOOK, README_FIRST, "STEALTH_README.md")


GOOD = (
    "diff --git a/CLAUDE.md b/CLAUDE.md\n"
    "index 43c994c2d3..15f6b4b0ab 100644\n"
    "--- a/CLAUDE.md\n+++ b/CLAUDE.md\n"
    "@@ -1 +1,2 @@\n"
    "+" + CLAUDE_HOOK + "\n"
    " @AGENTS.md\n"
    "diff --git a/README.md b/README.md\n"
    "index 01457dc066..f42282647e 100644\n"
    "--- a/README.md\n+++ b/README.md\n"
    "@@ -1,3 +1,5 @@\n"
    "+" + README_HOOK + "\n"
    "+\n"
    " " + README_FIRST + "\n"
    " \n"
    " [Firefox](https://firefox.com/) is a fast web browser\n"
)
MANIFEST = {"added": {"STEALTH_CLAUDE.md": "100644", "STEALTH_README.md": "100644"}}
SRC = {"STEALTH_CLAUDE.md", "STEALTH_README.md"}


def series_state():
    """(patch text, manifest, src files) of the series' platform/repo, or None while it does not hold the form."""
    if not (FOLDER / "hooks.patch").is_file():
        return None
    manifest = json.loads((FOLDER / "MANIFEST.json").read_text(encoding="utf-8"))
    if not {"STEALTH_CLAUDE.md", "STEALTH_README.md"} & set(manifest.get("added", {})):
        return None
    src = {p.name for p in (FOLDER / "src").glob("*") if p.is_file()}
    return (FOLDER / "hooks.patch").read_text(encoding="utf-8", errors="replace"), manifest, src


def test_claude_md_is_the_tag_plus_one_line_naming_a_file_that_exists():
    assert claude_md_problems(GOOD, MANIFEST, SRC) == []
    # red: Mozilla's file with our text inside it (the old form), a second line, the hook after @AGENTS.md
    inline = GOOD.replace("+" + CLAUDE_HOOK + "\n", "").replace(" @AGENTS.md\n", " @AGENTS.md\n+\n+# our text\n", 1)
    assert claude_md_problems(inline, MANIFEST, SRC)
    assert claude_md_problems(GOOD.replace("+" + CLAUDE_HOOK + "\n", "+" + CLAUDE_HOOK + "\n+more\n", 1), MANIFEST, SRC)
    after = GOOD.replace("+" + CLAUDE_HOOK + "\n @AGENTS.md\n", " @AGENTS.md\n+" + CLAUDE_HOOK + "\n", 1)
    assert claude_md_problems(after, MANIFEST, SRC)
    twice = GOOD.replace("+" + CLAUDE_HOOK + "\n", "+" + CLAUDE_HOOK + "\n+" + CLAUDE_HOOK + "\n", 1)
    assert claude_md_problems(twice, MANIFEST, SRC)
    # red: the file it points to is not ours (not in the MANIFEST, not in src/)
    assert claude_md_problems(GOOD, {"added": {}}, SRC)
    assert claude_md_problems(GOOD, MANIFEST, set())
    assert claude_md_problems("", MANIFEST, SRC)
    state = series_state()
    if state:
        assert claude_md_problems(*state) == []


def test_readme_md_is_the_tag_plus_one_line_naming_a_file_that_exists():
    assert readme_md_problems(GOOD, MANIFEST, SRC) == []
    # red: Mozilla's line removed, our text added after the banner, a second hook line, a missing target
    assert readme_md_problems(GOOD.replace(" " + README_FIRST + "\n", "-" + README_FIRST + "\n", 1), MANIFEST, SRC)
    later = GOOD.replace("+" + README_HOOK + "\n+\n " + README_FIRST + "\n",
                         " " + README_FIRST + "\n+" + README_HOOK + "\n+\n", 1)
    assert readme_md_problems(later, MANIFEST, SRC)
    twice = GOOD.replace("+" + README_HOOK + "\n", "+" + README_HOOK + "\n+" + README_HOOK + "\n", 1)
    assert readme_md_problems(twice, MANIFEST, SRC)
    assert readme_md_problems(GOOD, {"added": {"STEALTH_CLAUDE.md": "100644"}}, SRC)
    assert readme_md_problems(GOOD, MANIFEST, {"STEALTH_CLAUDE.md"})
    # a hook line that names another file
    assert readme_md_problems(GOOD.replace("STEALTH_README.md", "OTHER.md"), MANIFEST, SRC)
    state = series_state()
    if state:
        assert readme_md_problems(*state) == []
