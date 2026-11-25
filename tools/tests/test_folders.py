"""series-02, FOLDER.json (docs/decisions/series-02-every-folder-states-its-relation-to-mozilla.md): every folder of SERIES that is not a
backport states its relation to Mozilla in one hand-written FOLDER.json; `check` fails every other state of the series, and `port` stops
before it merges when a folder says Mozilla ships its fix in the new tag or before.

Shown on small series written for the purpose (the real series' values are the other branch's): each rule has the file that breaks it and
the shapes that do not.

    python -m pytest tools/tests/test_folders.py
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine  # noqa: E402
import folders  # noqa: E402
import layout  # noqa: E402
from seed_inventory import seed_inventory  # noqa: E402
from test_apply_builds_the_layer_stack import run, world  # noqa: E402,F401
from test_port import new_tag  # noqa: E402

TAG = "FIREFOX_159_0_RELEASE"
BUG = "https://bugzilla.mozilla.org/show_bug.cgi?id=1234567"
PRODUCT = {"relation": "product"}
DEFECT = {"relation": "defect", "upstream": "not-filed"}
RULE = "docs/decisions/series-02-every-folder-states-its-relation-to-mozilla.md"
REAL = Path(__file__).resolve().parents[2]


def series(tmp_path, spec, tag=TAG, stray=()):
    """spec: folder -> FOLDER.json (a dict, a raw string, or None for no file) or "backport" (a BACKPORT.json, no FOLDER.json)."""
    root = tmp_path / "series"
    root.mkdir(exist_ok=True)
    (root / "SERIES").write_text("\n".join(spec) + "\n", encoding="utf-8")
    (root / "UPSTREAM.json").write_text(json.dumps({"mozilla_tag": tag}), encoding="utf-8")
    for folder, value in spec.items():
        (root / folder).mkdir(parents=True, exist_ok=True)
        if value == "backport":
            (root / folder / "BACKPORT.json").write_text("{}", encoding="utf-8")
        elif isinstance(value, str):
            (root / folder / "FOLDER.json").write_text(value, encoding="utf-8")
        elif value is not None:
            (root / folder / "FOLDER.json").write_text(json.dumps(value), encoding="utf-8")
    for path in stray:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(json.dumps(PRODUCT), encoding="utf-8")
    return root


def one(tmp_path, value, **kw):
    return folders.problems(series(tmp_path, {"fingerprint/a": value}, **kw))


def said(problem):
    """Each problem says where, what, fix and rule, in that order."""
    found = re.fullmatch(r"FAIL (.+?)\. Fix: (.+)\. Rule: (.+)", problem, re.S)
    assert found, problem
    where_what, fix, rule = found.groups()
    assert fix.strip() and rule == RULE and "FOLDER.json" in where_what and ": " in where_what
    return where_what


# ---------------------------------------------------------------------------------------------------------------- what passes
@pytest.mark.parametrize("value", [
    PRODUCT,
    DEFECT,
    {"relation": "defect", "upstream": BUG},
    {"relation": "defect", "upstream": BUG, "fixed_in": "FIREFOX_160_0_RELEASE"},
    {"relation": "defect", "upstream": "not-filed", "fixed_in": "FIREFOX_159_0_1_RELEASE"},       # a patch release after 159.0 is after it
    {"relation": "defect", "upstream": BUG, "fixed_in": "FIREFOX_1000_0_RELEASE"},
])
def test_the_valid_shapes_pass(tmp_path, value):
    assert one(tmp_path, value) == []


def test_a_backport_has_no_folder_json_and_passes(tmp_path):
    root = series(tmp_path, {"platform/backports/x": "backport", "fingerprint/a": PRODUCT, "network/b": DEFECT})
    assert folders.problems(root) == []


# ---------------------------------------------------------------------------------------------------------------- what fails
def test_a_folder_without_the_file_is_red(tmp_path):
    found = one(tmp_path, None)
    assert len(found) == 1 and said(found[0]) == "fingerprint/a/FOLDER.json: the folder does not state its relation to Mozilla"
    assert '{"relation": "product"}' in found[0] and "not-filed" in found[0] and "bugzilla.mozilla.org/show_bug.cgi?id=<N>" in found[0]


def test_an_unknown_relation_is_red(tmp_path):
    for value in ({"relation": "ours"}, {"relation": "Product"}, {}, {"relation": None}, {"relation": ["product"]}):
        found = one(tmp_path, value)
        assert len(found) == 1 and "is not product or defect" in said(found[0]), value


def test_a_backport_written_by_hand_is_red(tmp_path):
    found = one(tmp_path, {"relation": "backport", "upstream": BUG})
    assert len(found) == 1 and 'relation "backport" is written by hand' in found[0] and "derived from BACKPORT.json" in found[0]


def test_a_folder_json_in_a_backport_folder_is_red(tmp_path):
    root = series(tmp_path, {"platform/backports/x": "backport"})
    (root / "platform/backports/x/FOLDER.json").write_text(json.dumps(PRODUCT), encoding="utf-8")
    found = folders.problems(root)
    assert len(found) == 1 and "it is a backport, and its relation is derived from that file" in said(found[0]) and "Fix: delete FOLDER.json" in found[0]


def test_an_extra_key_is_red(tmp_path):
    found = one(tmp_path, {"relation": "product", "note": "ours"})
    assert len(found) == 1 and "the key(s) 'note' are not allowed" in said(found[0])
    found = one(tmp_path, {"relation": "defect", "upstream": "not-filed", "bug": 1, "owner": "x"})
    assert len(found) == 1 and "'bug', 'owner'" in found[0]


def test_a_product_has_nothing_to_say_about_mozilla(tmp_path):
    found = one(tmp_path, {"relation": "product", "upstream": "not-filed"})
    assert len(found) == 1 and 'a product has no "upstream"' in said(found[0])
    found = one(tmp_path, {"relation": "product", "fixed_in": "FIREFOX_160_0_RELEASE"})
    assert len(found) == 1 and 'a product has no "fixed_in"' in said(found[0])


@pytest.mark.parametrize("upstream", [
    "https://example.invalid/bug/1",                                      # another URL
    "http://bugzilla.mozilla.org/show_bug.cgi?id=1",                      # not https
    "https://bugzilla.mozilla.org/show_bug.cgi?id=1&x=2",                 # more than the bug
    "https://bugzilla.mozilla.org/show_bug.cgi?id=0",
    "https://bugzilla.mozilla.org/show_bug.cgi?id=abc",
    "https://bugzilla.mozilla.org/show_bug.cgi?id=12 ",
    "https://github.com/mozilla-firefox/firefox/issues/1",
    "https://bugzilla.mozilla.org/show_bug.cgi?id=1#c4",
    "Not-Filed", "none", "", None, 1234567, ["not-filed"],
])
def test_an_upstream_that_is_neither_not_filed_nor_a_bugzilla_url_is_red(tmp_path, upstream):
    found = one(tmp_path, {"relation": "defect", "upstream": upstream})
    assert len(found) == 1 and "is neither not-filed nor a Mozilla bug URL" in said(found[0]) and "no other URL" in found[0]


@pytest.mark.parametrize("upstream", ["C:\\work\\notes\\bug.md", "/home/someone/notes.md", "../docs/bug.md", "docs/decisions/x.md", "file:///tmp/bug", "~/bug"])
def test_a_local_path_in_upstream_is_red(tmp_path, upstream):
    found = one(tmp_path, {"relation": "defect", "upstream": upstream})
    assert len(found) == 1 and "is neither not-filed nor a Mozilla bug URL" in found[0] and "no local path" in found[0]


def test_a_defect_without_upstream_is_red(tmp_path):
    found = one(tmp_path, {"relation": "defect"})
    assert len(found) == 1 and 'a defect has no "upstream"' in said(found[0])


@pytest.mark.parametrize("fixed", ["FIREFOX_159_0_RELEASE", "FIREFOX_158_0_RELEASE", "FIREFOX_99_0_RELEASE", "FIREFOX_58_0_2_RELEASE", "FIREFOX_159_0_0_RELEASE"])
def test_a_fixed_in_at_or_before_the_tag_is_red(tmp_path, fixed):
    found = one(tmp_path, {"relation": "defect", "upstream": BUG, "fixed_in": fixed})
    assert len(found) == 1
    assert "fixed_in %s is at or before the series' tag %s: Mozilla ships the fix" % (fixed, TAG) in said(found[0])
    assert "drop the folder" in found[0] and "rebase it onto Mozilla's fix" in found[0]


def test_release_tags_compare_by_version_not_by_name():
    assert folders.release_version("FIREFOX_99_0_RELEASE") < folders.release_version("FIREFOX_159_0_RELEASE")      # "99" > "159" as text
    assert folders.release_version("FIREFOX_159_0_RELEASE") < folders.release_version("FIREFOX_159_0_1_RELEASE") < folders.release_version("FIREFOX_160_0_RELEASE")
    assert folders.release_version("FIREFOX_160_0_1_RELEASE") == (160, 0, 1) and folders.release_version("FIREFOX_159_0_RELEASE") == (159, 0, 0)
    for bad in ("FIREFOX_159_0b3_RELEASE", "FIREFOX_159_0_ESR", "159", "", None, "FIREFOX_159_RELEASE", "firefox_159_0_release", "FIREFOX_159_0_RELEASE\n"):
        assert folders.release_version(bad) is None, bad


@pytest.mark.parametrize("fixed", ["FIREFOX_160_0b1_RELEASE", "nightly", "", None, 160, "FIREFOX_160_0_ESR"])
def test_a_fixed_in_that_is_not_a_release_tag_is_red(tmp_path, fixed):
    found = one(tmp_path, {"relation": "defect", "upstream": BUG, "fixed_in": fixed})
    assert len(found) == 1 and "is not a release tag" in said(found[0])


@pytest.mark.parametrize("raw", ["", "{", "[]", '"product"', "null", "{\"relation\": \"product\"}}"])
def test_a_file_that_is_not_a_json_object_is_red(tmp_path, raw):
    found = one(tmp_path, raw)
    assert len(found) == 1 and ("is not JSON" in found[0] or "is not a JSON object" in found[0]) and said(found[0])


def test_a_folder_json_outside_a_series_folder_is_red(tmp_path):
    root = series(tmp_path, {"fingerprint/audio/noise": PRODUCT}, stray=["fingerprint/audio/FOLDER.json", "FOLDER.json", "docs/FOLDER.json",
                                                                          "stillborn/unlisted/FOLDER.json", "fingerprint/audio/noise/deeper/FOLDER.json"])
    found = folders.problems(root)
    assert sorted(said(f).split(":")[0] for f in found) == ["FOLDER.json", "docs/FOLDER.json", "fingerprint/audio/FOLDER.json",
                                                            "fingerprint/audio/noise/deeper/FOLDER.json", "stillborn/unlisted/FOLDER.json"]
    assert all("a FOLDER.json outside a folder of SERIES" in f for f in found)


def test_a_file_of_ours_called_folder_json_under_src_is_not_the_folders_record(tmp_path):
    root = series(tmp_path, {"fingerprint/a": PRODUCT}, stray=["fingerprint/a/src/some/dir/FOLDER.json"])
    assert folders.problems(root) == []


def test_a_series_that_names_no_release_cannot_judge_fixed_in(tmp_path):
    found = folders.problems(series(tmp_path, {"fingerprint/a": PRODUCT}, tag="main"))
    assert len(found) == 1 and "mozilla_tag 'main' is not a release tag" in found[0] and found[0].endswith(RULE)


# ---------------------------------------------------------------------------------------------------------------- the real series
def real_series():
    return (REAL / "SERIES").read_text(encoding="utf-8").split()


def test_a_series_with_no_folder_json_is_red_in_every_folder_that_is_not_a_backport(tmp_path):
    """The state of the series before the values are written: the real list of folders, the real backports, no FOLDER.json."""
    names = real_series()
    backports = {f for f in names if (REAL / f / "BACKPORT.json").is_file()}
    assert backports and len(backports) < len(names)
    root = series(tmp_path, {f: ("backport" if f in backports else None) for f in names})
    found = folders.problems(root)
    assert len(found) == len(names) - len(backports) and all("the folder does not state its relation to Mozilla" in said(f) for f in found)
    assert {said(f).split("/FOLDER.json")[0] for f in found} == set(names) - backports


def test_no_backport_folder_of_the_real_series_has_a_folder_json():
    assert [f for f in real_series() if (REAL / f / "BACKPORT.json").is_file() and (REAL / f / "FOLDER.json").exists()] == []


def test_check_runs_the_folder_check(tmp_path, monkeypatch, capsys):
    root = series(tmp_path, {"fingerprint/a": None})
    monkeypatch.setattr(engine, "ROOT", root)
    monkeypatch.setattr(engine, "problems", lambda: [])
    monkeypatch.setattr(engine, "contract_problems", lambda *a, **k: ([], 0, 0))
    assert engine.check() == 1
    assert "FAIL fingerprint/a/FOLDER.json: the folder does not state its relation to Mozilla" in capsys.readouterr().out


# ---------------------------------------------------------------------------------------------------------------- port stops
def folder_files(series_root, a=None, b=None):
    for name, value in (("fingerprint/a", a), ("platform/b", b)):
        path = series_root / name / "FOLDER.json"
        path.write_text(json.dumps(value), encoding="utf-8") if value is not None else None


def test_fixed_in_stops_lists_the_folders_whose_fix_is_in_the_new_tag_or_before(tmp_path):
    root = series(tmp_path, {"fingerprint/a": {"relation": "defect", "upstream": BUG, "fixed_in": "FIREFOX_160_0_RELEASE"},
                             "platform/b": {"relation": "defect", "upstream": "not-filed", "fixed_in": "FIREFOX_161_0_RELEASE"},
                             "network/c": PRODUCT, "stillborn/d": "backport", "automation/e": "{"})
    assert folders.fixed_in_stops(root, "FIREFOX_159_0_RELEASE") == []
    assert folders.fixed_in_stops(root, "FIREFOX_160_0_RELEASE") == [("fingerprint/a", "FIREFOX_160_0_RELEASE")]
    assert folders.fixed_in_stops(root, "FIREFOX_160_0_1_RELEASE") == [("fingerprint/a", "FIREFOX_160_0_RELEASE")]
    assert [f for f, _ in folders.fixed_in_stops(root, "FIREFOX_162_0_RELEASE")] == ["fingerprint/a", "platform/b"]


def test_port_stops_before_it_merges_when_a_fix_is_in_the_new_tag(world, capsys):
    new_tag(world, "FIREFOX_160_0_RELEASE", b"zero\none\ntwo\n")
    folder_files(engine.ROOT, {"relation": "defect", "upstream": BUG, "fixed_in": "FIREFOX_160_0_RELEASE"}, PRODUCT)
    with pytest.raises(SystemExit) as stop:
        engine.port(world, "TAG", "FIREFOX_160_0_RELEASE", "port/x", force=False)
    message = str(stop.value.code)
    assert stop.value.code not in (0, None) and isinstance(stop.value.code, str), "a non-zero exit with the message"
    assert "port stopped before it merged anything: 1 folder(s) say Mozilla ships their fix in FIREFOX_160_0_RELEASE or before" in message
    assert "  fingerprint/a: fixed_in FIREFOX_160_0_RELEASE" in message and "platform/b" not in message
    assert "next: python tools/engine.py port --to FIREFOX_160_0_RELEASE --source <source>" in message and "export" in message and RULE.replace("rule:", "Rule:") in message
    assert subprocess.run(["git", "-C", str(world), "rev-parse", "-q", "--verify", "refs/heads/port/x"], capture_output=True).returncode != 0, "nothing merged"
    assert capsys.readouterr().out == "", "it stopped, it did not print and go on"


def test_port_stops_when_the_fix_is_before_the_new_tag(world):
    new_tag(world, "FIREFOX_160_0_RELEASE", b"zero\none\ntwo\n")
    folder_files(engine.ROOT, None, {"relation": "defect", "upstream": "not-filed", "fixed_in": "FIREFOX_150_0_RELEASE"})
    with pytest.raises(SystemExit) as stop:
        engine.port(world, "TAG", "FIREFOX_160_0_RELEASE", "port/x", force=False)
    assert "platform/b: fixed_in FIREFOX_150_0_RELEASE" in str(stop.value.code)


def test_port_goes_on_when_every_fix_is_after_the_new_tag(world):
    new_tag(world, "FIREFOX_160_0_RELEASE", b"zero\none\ntwo\n")
    folder_files(engine.ROOT, {"relation": "defect", "upstream": BUG, "fixed_in": "FIREFOX_161_0_RELEASE"}, PRODUCT)
    assert engine.port(world, "TAG", "FIREFOX_160_0_RELEASE", "port/x", force=False) == 0
    assert run(world, "log", "--format=%s", "FIREFOX_160_0_RELEASE..port/x").splitlines() == ["fingerprint/a", "platform/b"]


def test_the_command_stops_with_a_non_zero_exit(world, monkeypatch):
    new_tag(world, "FIREFOX_160_0_RELEASE", b"zero\none\ntwo\n")
    folder_files(engine.ROOT, {"relation": "defect", "upstream": "not-filed", "fixed_in": "FIREFOX_160_0_RELEASE"}, PRODUCT)
    monkeypatch.setattr(sys, "argv", ["engine.py", "port", "--to", "FIREFOX_160_0_RELEASE", "--base", "TAG", "--source", str(world)])
    with pytest.raises(SystemExit) as stop:
        engine.main()
    assert isinstance(stop.value.code, str) and "next: python tools/engine.py port --to FIREFOX_160_0_RELEASE" in stop.value.code


# ---------------------------------------------------------------------------------------------------------------- export leaves it alone
def test_export_never_writes_or_deletes_a_folder_json(world, tmp_path, monkeypatch):
    """The relation is the author's, by hand: export writes hooks.patch, src/, MANIFEST.json, FEATURE.md and HOOKS.json, and removes a folder
    that owns nothing any more (with whatever is in it); it neither creates a FOLDER.json nor touches one in a folder that stays."""
    run(world, "checkout", "-q", "-B", "work", "TAG")
    engine.apply(world, "TAG", "series", force=False)
    root = engine.ROOT
    keep = {"fingerprint/a": b'{"relation": "defect", "upstream": "not-filed"}\n', "platform/b": b'{"relation": "product"}\n'}
    for name, data in keep.items():
        (root / name / "FOLDER.json").write_bytes(data)
    gone = root / "port" / "gone"
    gone.mkdir(parents=True)
    (gone / "MANIFEST.json").write_text(json.dumps({"modified": [], "added": {}}), encoding="utf-8")
    (gone / "FOLDER.json").write_bytes(b'{"relation": "product"}\n')
    (root / "SERIES").write_text("platform/b\nfingerprint/a\nport/gone\n", encoding="utf-8")
    upstream = tmp_path / "UPSTREAM.json"
    upstream.write_text(json.dumps({"mozilla_tag": "TAG", "source_branch": "series"}), encoding="utf-8")
    for name in ("BUDGET", "REMOVED_BUDGET"):      # export writes the entry of a file patched for the first time: into a copy
        (tmp_path / (name + ".json")).write_text("{}", encoding="utf-8")
        monkeypatch.setattr(engine, name, tmp_path / (name + ".json"))
    monkeypatch.setattr(engine, "UPSTREAM", upstream)
    monkeypatch.setattr(engine, "WORKFLOWS_SERIES", tmp_path / "wf-series")
    monkeypatch.setattr(engine, "WORKFLOWS_ROOT", tmp_path / "wf-root")
    monkeypatch.setattr(layout, "feature_folder", lambda feature: "fingerprint/a")
    monkeypatch.setattr(layout, "own_file_folder", lambda path, held, declared=None: "fingerprint/a" if path.startswith("dom/") else "platform/b")
    monkeypatch.setattr(layout, "GROUP_ORDER", ["platform", "fingerprint", "port"])
    seed_inventory(root, [{"file": "mozilla.txt", "feature": "x", "category": "hook", "hookable": "yes"}])
    engine.export(world, "TAG", "series")
    for name, data in keep.items():
        assert (root / name / "FOLDER.json").read_bytes() == data, "%s: its FOLDER.json is as the author wrote it" % name
    assert not gone.exists(), "a folder that owns nothing goes whole, as before"
    # a folder export makes anew has none: the author writes it
    run(world, "checkout", "-q", "-B", "more", "series")
    (world / "net.txt").write_text("x\n", encoding="utf-8")
    run(world, "add", "net.txt")
    run(world, "commit", "-qm", "net")
    monkeypatch.setattr(layout, "own_file_folder", lambda path, held, declared=None: "fingerprint/n" if path == "net.txt" else
                        ("fingerprint/a" if path.startswith("dom/") else "platform/b"))
    engine.export(world, "TAG", "more")
    assert (root / "fingerprint" / "n" / "MANIFEST.json").is_file() and not (root / "fingerprint" / "n" / "FOLDER.json").exists()
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob("FOLDER.json")) == ["fingerprint/a/FOLDER.json", "platform/b/FOLDER.json"]   # rglob has no order: NTFS gives the sorted one, ext4 does not


def test_the_command_prints_each_problem_as_one_fail_line_of_four_parts(tmp_path, capsys):
    root = series(tmp_path, {"fingerprint/a": None})
    assert folders.main([str(root)]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1 and lines[0].startswith("FAIL fingerprint/a/FOLDER.json: ") and lines[0].count("FAIL ") == 1
    assert said(lines[0]) and " Fix: " in lines[0] and lines[0].endswith("Rule: " + RULE)
