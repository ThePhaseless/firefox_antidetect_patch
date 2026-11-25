"""repo-05: `python tools/engine.py` is the one front door, and every command that stops ends with the command to run next.

  * the front door (no argument, or --help) prints the state of the series, every command with one line, and `next:`;
  * every stop path of every command ends with `next: <exact command>`, and that command is a subcommand the parser knows, with
    the arguments it needs (a source for the commands that read it, a tag for `port` and `drift`);
  * `port` writes `mozilla_tag` and `source_branch` of UPSTREAM.json itself, so no step of docs/UPDATE.md types them;
  * no step of docs/UPDATE.md is a hand edit of a file a command writes (the fields of UPSTREAM.json, the `tag` of the births ledger).

Shown on the two-file repository of test_apply_builds_the_layer_stack.py, so it runs anywhere.

    python -m pytest -q tools/tests/test_front_door.py
"""
import ast
import inspect
import json
import re
import shlex
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1]
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine  # noqa: E402
import export_gate  # noqa: E402
import births  # noqa: E402
import hook_contract  # noqa: E402
from failure import fail  # noqa: E402
from test_apply_builds_the_layer_stack import run, world  # noqa: E402,F401
from test_port import new_tag  # noqa: E402

DELEGATED = {"births", "prebuild", "range-diff"}       # parsed by their own tools


def last_line(text: str) -> str:
    return [l for l in text.strip().splitlines() if l.strip()][-1]


def assert_next(text: str) -> str:
    """The text ends with `next: python tools/engine.py <subcommand> <arguments>` that the parser accepts and that would not stop at once
    for lack of an argument. Returns the subcommand."""
    line = last_line(text)
    assert line.startswith("next: "), "a stop does not end with next:\n" + text
    tokens = shlex.split(line[len("next: "):])
    assert tokens[:2] == ["python", "tools/engine.py"], line
    args = tokens[2:]
    if not args:
        return ""                                               # the front door
    assert args[0] in engine.COMMAND_NAMES, "next: names no subcommand: " + line
    if args[0] in DELEGATED:
        if args[0] == "births":
            flags = set(re.findall(r'"(--[a-z-]+)"', inspect.getsource(births.main)))
            assert {a for a in args[1:] if a.startswith("--")} <= flags, line
        return args[0]
    ns = engine.build_parser().parse_args(args)                 # exits on an unknown option or a bad choice
    assert ns.command == args[0]
    if ns.command in engine.SOURCE_COMMANDS:
        assert ns.source is not None, "next: would stop at once, it names no --source: " + line
    if ns.command in ("drift", "port"):
        assert ns.to, "next: would stop at once, it names no --to: " + line
    return ns.command


def stop_text(call) -> str:
    with pytest.raises(SystemExit) as stop:
        call()
    assert isinstance(stop.value.code, str), "a stop prints its message"
    return stop.value.code


@pytest.fixture
def upstream_file(tmp_path, monkeypatch, world):
    path = tmp_path / "UPSTREAM.json"
    path.write_text(json.dumps({"mozilla_repository": "https://example.invalid/firefox", "mozilla_tag": "TAG", "source_branch": "work",
                                "exported_from": "0" * 40, "exported_tree": "1" * 40}), encoding="utf-8")
    monkeypatch.setattr(engine, "UPSTREAM", path)
    return path


# --------------------------------------------------------------------------------------------------- the front door
def test_the_front_door_names_the_state_every_command_and_the_next_one(capsys, monkeypatch, upstream_file):
    monkeypatch.setattr(sys, "argv", ["engine.py"])
    monkeypatch.delenv("FIREFOX_SOURCE", raising=False)
    assert engine.entry() == 0
    out = capsys.readouterr().out
    assert "mozilla_tag TAG" in out and "source_branch work" in out and "exported_from " + "0" * 40 in out
    for name in engine.COMMAND_NAMES:
        assert re.search(r"^  %s +\S" % re.escape(name), out, re.M), "the front door does not list %s with a line" % name
    assert last_line(out) == "next: python tools/engine.py status --source <source>"
    assert assert_next(out) == "status"


def test_help_is_the_front_door(capsys, monkeypatch, upstream_file):
    monkeypatch.setattr(sys, "argv", ["engine.py", "--help"])
    assert engine.entry() == 0
    out = capsys.readouterr().out
    assert "commands:" in out and "series: mozilla_tag" in out and last_line(out).startswith("next: ")


def test_every_parser_choice_is_listed_by_the_front_door():
    parser = engine.build_parser()
    choices = [a for a in parser._actions if a.dest == "command"][0].choices
    assert sorted(choices) == sorted(engine.COMMAND_NAMES)
    assert all(line for _, line in engine.COMMAND_LINES)


def test_the_front_door_with_the_source_in_step_says_check(world, upstream_file, monkeypatch, capsys):
    engine.apply(world, "TAG", "work", force=False)
    data = json.loads(upstream_file.read_text())
    data["exported_from"] = run(world, "rev-parse", "work")
    upstream_file.write_text(json.dumps(data))
    monkeypatch.setattr(sys, "argv", ["engine.py", "--source", str(world)])
    assert engine.entry() == 0
    out = capsys.readouterr().out
    assert "source: work is %s, equal to exported_from" % data["exported_from"][:10] in out
    assert "verify would pass" in out
    assert last_line(out) == "next: python tools/engine.py check" and assert_next(out) == "check"


def test_the_front_door_with_the_source_moved_says_export(world, upstream_file, monkeypatch, capsys):
    engine.apply(world, "TAG", "work", force=False)
    monkeypatch.setattr(sys, "argv", ["engine.py", "--source", str(world)])
    assert engine.entry() == 0
    out = capsys.readouterr().out
    assert ", not exported_from" in out and "verify would pass" in out
    assert last_line(out) == "next: python tools/engine.py export --source <source> --head work" and assert_next(out) == "export"


def test_the_front_door_says_when_the_series_does_not_rebuild_the_head(world, upstream_file, monkeypatch, capsys):
    engine.apply(world, "TAG", "work", force=False)
    run(world, "checkout", "-q", "work")
    (world / "mozilla.txt").write_bytes(b"one\nhook();\ntwo\nmore\n")
    run(world, "commit", "-qam", "a change the series does not have")
    monkeypatch.setattr(sys, "argv", ["engine.py", "--source", str(world)])
    assert engine.entry() == 0
    out = capsys.readouterr().out
    assert "verify would fail" in out and last_line(out).startswith("next: python tools/engine.py export")


def test_the_front_door_without_the_branch_says_apply(world, upstream_file, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["engine.py", "--source", str(world)])
    assert engine.entry() == 0
    out = capsys.readouterr().out
    assert "has no branch work" in out
    assert last_line(out) == "next: python tools/engine.py apply --source <source> --head work" and assert_next(out) == "apply"


# --------------------------------------------------------------------------------------------------- every stop ends with next:
def test_apply_onto_an_existing_branch_ends_with_next_apply_force(world):
    engine.apply(world, "TAG", "work", force=False)
    text = stop_text(lambda: engine.apply(world, "TAG", "work", force=False))
    assert assert_next(text) == "apply" and "--force" in last_line(text)


def test_a_series_that_does_not_apply_on_the_tag_ends_with_next(world):
    run(world, "checkout", "-q", "-B", "other", "TAG")
    (world / "mozilla.txt").write_bytes(b"completely\ndifferent\n")
    run(world, "commit", "-qam", "other")
    run(world, "tag", "OTHER")
    text = stop_text(lambda: engine.apply(world, "OTHER", "x", force=False))
    assert "fingerprint/a/hooks.patch: it does not apply on OTHER" in text and assert_next(text)


def test_a_branch_that_does_not_descend_from_the_tag_ends_with_next(world):
    run(world, "checkout", "-q", "--orphan", "elsewhere")
    run(world, "commit", "-q", "--allow-empty", "-m", "unrelated")
    for call in (lambda: engine.verify(world, "TAG", "elsewhere"), lambda: engine.export(world, "TAG", "elsewhere")):
        text = stop_text(call)
        assert "does not descend from TAG" in text and assert_next(text) == "apply"


def test_verify_that_finds_a_difference_ends_with_next_export(world, capsys):
    engine.apply(world, "TAG", "work", force=False)
    run(world, "checkout", "-q", "work")
    (world / "mozilla.txt").write_bytes(b"one\nhook();\ntwo\nmore\n")
    run(world, "commit", "-qam", "edited in the source only")
    assert engine.verify(world, "TAG", "work") == 1
    out = capsys.readouterr().out
    assert "DIFFERENT" in out and "Rule: docs/decisions/series-01-export-is-the-only-writer.md" in out
    assert assert_next(out) == "export"


def test_export_of_a_file_nobody_owns_ends_with_next(world, tmp_path, monkeypatch):
    run(world, "checkout", "-q", "-B", "modified", "TAG")
    (world / "mozilla.txt").write_bytes(b"one\nhook();\ntwo\nmore\n")
    run(world, "commit", "-qam", "a modified file with no record")
    text = stop_text(lambda: engine.export(world, "TAG", "modified"))
    assert "the modified file mozilla.txt has no record" in text and "Rule: docs/decisions/series-01" in text and assert_next(text) == "export"
    run(world, "checkout", "-q", "-B", "added", "TAG")
    (world / "nowhere").mkdir()
    (world / "nowhere" / "own.txt").write_bytes(b"ours\n")
    run(world, "add", ".")
    run(world, "commit", "-qm", "a file of ours no folder owns")
    text = stop_text(lambda: engine.export(world, "TAG", "added"))
    assert "no folder owns our new file: nowhere/own.txt" in text and "--own nowhere/own.txt=<folder>" in text
    assert assert_next(text) == "export"


def test_port_stops_end_with_next_port(world, upstream_file):
    new_tag(world, "NEW", b"zero\none\ntwo\n")
    missing = stop_text(lambda: engine.port(world, "TAG", "NOPE", "port/NOPE", force=False))
    assert "git -C" in missing and "refs/tags/NOPE" in missing and assert_next(missing) == "port"
    engine.port(world, "TAG", "NEW", "port/NEW", force=False)
    exists = stop_text(lambda: engine.port(world, "TAG", "NEW", "port/NEW", force=False))
    assert assert_next(exists) == "port" and "--force" in last_line(exists) and "--head port/NEW" in last_line(exists)
    same = stop_text(lambda: engine.port(world, "NEW", "NEW", "port/x", force=False))
    assert "already NEW" in same and "--base <old-tag>" in last_line(same) and assert_next(same) == "port"


def test_port_with_conflicts_ends_with_next_export(world, upstream_file, capsys):
    new_tag(world, "NEW", b"one\nTWO CHANGED\n")
    assert engine.port(world, "TAG", "NEW", "port/NEW", force=False, check_births=False) == 1
    out = capsys.readouterr().out
    assert "CONFLICT fingerprint/a: mozilla.txt" in out and "Rule: docs/decisions/port-01-one-run.md" in out
    assert last_line(out) == "next: python tools/engine.py export --source <source>" and assert_next(out) == "export"


def test_the_commands_that_need_an_argument_end_with_next(monkeypatch, upstream_file, capsys):
    monkeypatch.delenv("FIREFOX_SOURCE", raising=False)
    for argv, expected in ((["engine.py", "status"], "status"), (["engine.py", "port", "--to", "T"], "port"), (["engine.py", "drift"], "drift"),
                           (["engine.py", "port", "--source", "x"], "port")):
        monkeypatch.setattr(sys, "argv", argv)
        try:
            engine.entry()
        except SystemExit as stop:
            text = stop.code
        else:
            pytest.fail("%s did not stop" % argv)
        assert isinstance(text, str) and assert_next(text) == expected, text


def test_a_wrong_command_line_ends_with_next(monkeypatch, capsys, upstream_file):
    monkeypatch.setattr(sys, "argv", ["engine.py", "no-such-command"])
    with pytest.raises(SystemExit) as stop:
        engine.entry()
    assert stop.value.code == 2
    err = capsys.readouterr().err
    assert "Rule: docs/decisions/series-01" in err and assert_next(err) == ""


def test_status_that_finds_the_source_moved_ends_with_next_export(world, upstream_file, capsys):
    engine.apply(world, "TAG", "work", force=False)
    data = json.loads(upstream_file.read_text())
    data["exported_from"] = run(world, "rev-parse", "TAG")
    upstream_file.write_text(json.dumps(data))
    assert engine.status(world, "work") == 1
    out = capsys.readouterr().out
    assert "run export, then verify" in out and assert_next(out) == "export"


def test_check_that_finds_a_problem_ends_with_next_check(monkeypatch, capsys):
    monkeypatch.setattr(engine, "problems", lambda: [fail("SERIES", "a problem", "export again", "series-01-export-is-the-only-writer")])
    monkeypatch.setattr(engine.folders, "problems", lambda root: [])
    monkeypatch.setattr(engine, "contract_problems", lambda *a, **k: ([], 0, 0))
    assert engine.check(None, None, against_main=False) == 1
    out = capsys.readouterr().out
    assert out.startswith("FAIL SERIES: a problem.") and "FAIL FAIL" not in out and assert_next(out) == "check"


def test_the_hook_debt_and_locals_stops_end_with_next(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(engine, "HOOK_DEBT", tmp_path / "missing.json")
    monkeypatch.setattr(engine.hook_contract, "contract_violations", lambda root: [])
    text = stop_text(lambda: engine.hook_debt())
    assert "tools/hook-debt.json" in text and assert_next(text) == "hook-debt"
    found = [hook_contract.Violation("C16", "fingerprint/a", "mozilla.txt", "void F() {", "Use(local);", "key", detail="passes a local")]
    monkeypatch.setattr(engine.hook_contract, "git_base_reader", lambda source, tag: None)
    monkeypatch.setattr(engine.hook_contract, "locals_violations", lambda root, base: found)
    monkeypatch.setattr(engine.hook_contract, "namespace_violations", lambda root, unqualified=False: [])
    assert engine.hook_locals(Path("src"), "TAG") == 1
    out = capsys.readouterr().out
    assert assert_next(out) == "export"
    assert out.splitlines()[0] == str(hook_contract.violation_failure(found[0])) and out.startswith("FAIL fingerprint/a/hooks.patch")


def test_a_missing_origin_main_ends_with_next(tmp_path, monkeypatch):
    run(tmp_path, "init", "-q")
    monkeypatch.setattr(engine, "ROOT", tmp_path)
    text = stop_text(engine.ensure_main_ref)
    assert "origin/main" in text and "Rule: docs/decisions/hook-03" in text and assert_next(text) == "check"


def test_the_export_gate_ends_with_next_export(monkeypatch, tmp_path):
    monkeypatch.delenv("ENGINE_NODE_GATE_TREE", raising=False)
    text = stop_text(lambda: export_gate.gate(tmp_path, "work", lambda scratch: None, tmp_path))
    assert "ENGINE_NODE_GATE_TREE" in text and "Rule: docs/decisions/series-01" in text
    assert last_line(text) == "next: python tools/engine.py export --source <source> --head work" and assert_next(text) == "export"
    monkeypatch.setenv("ENGINE_NODE_GATE_TREE", str(tmp_path / "tree"))
    monkeypatch.setenv("ENGINE_NODE", str(tmp_path / "no-node"))
    monkeypatch.setattr(export_gate.shutil, "which", lambda name: None)
    text = stop_text(lambda: export_gate.gate(tmp_path, "work", lambda scratch: None, tmp_path))
    assert "no Node" in text and assert_next(text) == "export"


def test_a_failed_git_command_is_a_failure_with_next(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["engine.py", "status", "--source", str(tmp_path / "not-a-repository")])
    monkeypatch.setattr(engine, "upstream", lambda: {"mozilla_tag": "TAG", "source_branch": "work", "exported_from": "0" * 40})
    with pytest.raises(SystemExit) as stop:
        engine.entry()
    text = stop.value.code
    assert text.startswith("FAIL git ") and "Rule: docs/decisions/series-01" in text and assert_next(text) == "status"


# --------------------------------------------------------------------------------------------------- the next commands in the source
def test_every_command_the_source_names_is_a_subcommand():
    """Every `command(<name>, ...)` call of engine.py starts with a subcommand the parser knows; so does each literal command line
    printed by export_gate.py."""
    tree = ast.parse((TOOLS / "engine.py").read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "command"]
    assert len(calls) > 20
    for call in calls:
        if not call.args:
            continue
        first = call.args[0]
        if isinstance(first, ast.Starred):
            continue                                            # command(*parts): the parts are tested where they are built
        if isinstance(first, ast.Constant):
            assert first.value in engine.COMMAND_NAMES, "engine.py:%d names no subcommand: %r" % (call.lineno, first.value)
        else:
            assert isinstance(first, ast.Attribute) and first.attr == "command" or isinstance(first, ast.Name), "engine.py:%d" % call.lineno
    gate = (TOOLS / "export_gate.py").read_text(encoding="utf-8")
    for name in re.findall(r"python tools/engine\.py (\S+)", gate):
        assert name in engine.COMMAND_NAMES, name


# --------------------------------------------------------------------------------------------------- port writes UPSTREAM.json
def test_port_writes_the_tag_and_the_branch_it_made(world, upstream_file):
    new_tag(world, "NEW", b"zero\none\ntwo\n")
    assert engine.port(world, "TAG", "NEW", "port/NEW", force=False, record_upstream=upstream_file) == 0
    data = json.loads(upstream_file.read_text())
    assert data["mozilla_tag"] == "NEW" and data["source_branch"] == "port/NEW"
    assert data["exported_from"] == "0" * 40 and data["exported_tree"] == "1" * 40, "the export's fields stay the export's"
    assert data["mozilla_repository"] == "https://example.invalid/firefox"


def test_a_port_with_conflicts_writes_them_too(world, upstream_file):
    new_tag(world, "NEW", b"one\nTWO CHANGED\n")
    assert engine.port(world, "TAG", "NEW", "port/NEW", force=False, record_upstream=upstream_file) == 1
    assert json.loads(upstream_file.read_text())["mozilla_tag"] == "NEW", "the export that follows the resolution needs no hand edit"


def test_a_port_that_stops_before_it_merges_writes_nothing(world, upstream_file):
    before = upstream_file.read_text()
    with pytest.raises(SystemExit):
        engine.port(world, "TAG", "NOPE", "port/NOPE", force=False, record_upstream=upstream_file)
    new_tag(world, "NEW", b"zero\none\ntwo\n")
    engine.port(world, "TAG", "NEW", "port/NEW", force=False)
    with pytest.raises(SystemExit):
        engine.port(world, "TAG", "NEW", "port/NEW", force=False, record_upstream=upstream_file)       # the branch exists
    assert upstream_file.read_text() == before


def test_the_port_command_writes_upstream_json_and_a_second_run_names_the_old_tag(world, upstream_file, monkeypatch, capsys):
    new_tag(world, "NEW", b"zero\none\ntwo\n")
    monkeypatch.setattr(sys, "argv", ["engine.py", "port", "--to", "NEW", "--source", str(world)])
    assert engine.entry() == 0
    data = json.loads(upstream_file.read_text())
    assert (data["mozilla_tag"], data["source_branch"]) == ("NEW", "port/NEW")
    assert "UPSTREAM.json: mozilla_tag NEW, source_branch port/NEW" in capsys.readouterr().out
    text = stop_text(engine.entry)                      # run again: the tag is already NEW
    assert "--base <old-tag>" in last_line(text) and assert_next(text) == "port"
    monkeypatch.setattr(sys, "argv", ["engine.py", "port", "--to", "NEW", "--source", str(world), "--base", "TAG", "--head", "port/other"])
    assert engine.entry() == 0
    assert json.loads(upstream_file.read_text())["source_branch"] == "port/other"


# --------------------------------------------------------------------------------------------------- docs/UPDATE.md
FIELD = r"(?:UPSTREAM\.json|mozilla_tag|source_branch|exported_from|exported_tree)"
HAND_EDIT = re.compile(r"UPSTREAM\.json[^.]{0,40}by hand|by hand[^.]{0,40}UPSTREAM\.json"
                       r"|\b(?:change|edit|set|type|write)\b[^.|]{0,20}`?" + FIELD + r"`?"
                       r"|`(?:mozilla_tag|source_branch)` to `", re.I)
WRITTEN_BY_A_COMMAND = re.compile(r"\bwrites?\b|\bwrote\b|no step types", re.I)


def hand_edits(text: str) -> list:
    """The lines of a doc that tell the reader to edit by hand a field a command writes: a field of UPSTREAM.json (mozilla_tag,
    source_branch, exported_from, exported_tree) or the `tag` of the births ledger."""
    found = []
    for no, line in enumerate(text.splitlines(), 1):
        if HAND_EDIT.search(line) and not WRITTEN_BY_A_COMMAND.search(line):
            found.append("%d: %s" % (no, line.strip()))
        elif re.search(r"\bledger\b", line, re.I) and re.search(r"`tag`", line) and re.search(r"by hand|\bset\b|\bedit", line, re.I) \
                and not re.search(r"derived|no step types", line):
            found.append("%d: %s" % (no, line.strip()))
        elif re.search(r"Set `tag`", line):
            found.append("%d: %s" % (no, line.strip()))
    return found


@pytest.mark.parametrize("line", [
    "In `UPSTREAM.json`, by hand: `mozilla_tag` to `NEW`, `source_branch` to the branch of step 4.",
    "Then: resolve the markers on that branch, change `mozilla_tag` in `UPSTREAM.json`, and export.",
    "Set `tag` in the ledger to `NEW`. Exit 0 is clean",
    "| `tag` of the birth ledger | `tools/birth-ledger.json` | Set by hand (step 7) |",
])
def test_the_check_of_the_doc_sees_a_hand_edit(line):
    assert hand_edits(line), "the check does not see: " + line


def test_no_step_of_update_md_edits_by_hand_what_a_command_writes():
    text = (REPO / "docs" / "UPDATE.md").read_text(encoding="utf-8")
    assert hand_edits(text) == []
    assert "python tools/engine.py export --source <source>\n" in text and "--head port/$NEW\npython tools/engine.py verify" not in text


def test_update_md_says_that_port_writes_the_tag_and_the_branch():
    text = (REPO / "docs" / "UPDATE.md").read_text(encoding="utf-8")
    assert "It writes `mozilla_tag` (`NEW`) and `source_branch`" in text and "`python tools/engine.py` (no argument)" in text
