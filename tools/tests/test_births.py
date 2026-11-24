"""The birth-point gate (tools/births.py), each rule shown failing on the input it exists for.

A request a page causes gets its proxy and its resolver from the user context in its origin attributes. A call that creates a channel, a socket, a
lookup or a speculative connection with the default attributes, the system principal or a plain socket leaves the context's proxy. The ledger holds a
reviewed verdict for every such call of the tree; these tests run the scanner and the judge on small texts (no Firefox, no git except in the last two)
and break one thing at a time:

  * a call the ledger does not have is NEW and red;
  * a call whose statement, or whose function's context signature, is not the one reviewed is CHANGED and red;
  * a line that only moved is not red (the key is file + function + kind + call + ordinal, never the line);
  * a site that carries no context and that a page can reach is red unless it is accepted, hooked or dead; a hook that is gone is red;
  * the open items (a dated known hole) are counted and give exit status 2, and hide nothing new, which is still 1;
  * the false friend: `NullPrincipal::Create(attrs)` carries the attributes, `CreateWithoutOriginAttributes()` does not.

    python -m pytest tools/tests/test_births.py
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import births  # noqa: E402

FILE = "netwerk/base/Loader.cpp"

CARRIES = """\
#include "nsNetUtil.h"

nsresult Loader::Open(nsIURI* aURI, Document* aDoc) {
  nsCOMPtr<nsIChannel> channel;
  nsresult rv = NS_NewChannel(getter_AddRefs(channel), aURI, aDoc,
                              nsILoadInfo::SEC_ALLOW_CROSS_ORIGIN_SEC_CONTEXT_IS_NULL,
                              nsIContentPolicy::TYPE_OTHER);
  NS_ENSURE_SUCCESS(rv, rv);
  return NS_OK;
}
"""

SYSTEM = """\
nsresult Probe::Fetch(nsIURI* aURI, const OriginAttributes& aAttrs) {
  nsCOMPtr<nsIChannel> channel;
  nsresult rv = NS_NewChannel(getter_AddRefs(channel), aURI,
                              nsContentUtils::GetSystemPrincipal(),
                              nsILoadInfo::SEC_ALLOW_CROSS_ORIGIN_SEC_CONTEXT_IS_NULL,
                              nsIContentPolicy::TYPE_OTHER);
  nsCOMPtr<nsILoadInfo> loadInfo = channel->LoadInfo();
  loadInfo->SetOriginAttributes(aAttrs);
  return rv;
}
"""


def entry(site, **kw):
    e = dict(file=site.file, function=site.function, kind=site.kind, call=site.call, n=site.n, stmt_sha=site.stmt_sha, ctx_sig=site.ctx_sig,
             carries="yes", reach="yes", verdict="ok", reason="the document of the load carries the attributes of its context")
    e.update(kw)
    return e


def ledger_of(*texts, **kw):
    sites = [s for path, text in texts for s in births.scan_text(path, text)]
    return {"tag": "T", "scanner": 1, "chrome_js_http": {}, "entries": sorted((entry(s, **kw) for s in sites), key=births.entry_key)}, sites


def judge(ledger, sites, read=None):
    return births.judge(ledger, sites, read=read, folders={"network/doh", "network/proxy-udp"})


# ------------------------------------------------------------------------------------------------------------------ the scanner
def test_a_call_is_found_with_its_function_kind_and_ordinal():
    sites = births.scan_text(FILE, CARRIES)
    assert [(s.file, s.function, s.kind, s.call, s.n) for s in sites] == [(FILE, "Loader::Open", "channel", "NS_NewChannel", 1)]
    assert sites[0].line == 5 and "aDoc" in sites[0].stmt and "TYPE_OTHER" in sites[0].stmt     # the whole statement, not the first line


def test_two_calls_of_a_function_are_numbered_in_order():
    twice = CARRIES.replace("  return NS_OK;", "  rv = NS_NewChannel(getter_AddRefs(channel), aURI, aDoc, 1, 2);\n  return NS_OK;")
    assert [s.n for s in births.scan_text(FILE, twice)] == [1, 2]


def test_a_comment_holds_no_birth_point_and_a_regex_literal_does_not_open_one():
    assert births.scan_text(FILE, "// rv = NS_NewChannel(a, b, c);\n/* NS_NewChannel(x) */\nvoid f() {}\n") == []
    js = "const re = /^(?:[a-z+.-]+:\\/*(?!\\/))?x/i;\nfunction go() {\n  Services.dns.asyncResolve(\n    host,\n  );\n}\n"
    sites = births.scan_text("docshell/base/Fixup.sys.mjs", js)
    assert [(s.function, s.kind, s.call) for s in sites] == [("go", "dns_async_js", "asyncResolve")]


def test_a_declaration_or_a_definition_of_the_call_is_not_a_call():
    definition = "nsresult nsDNSService::AsyncResolveNative(const nsACString& aHost, nsresult x) {\n  return NS_OK;\n}\n"
    assert births.scan_text("netwerk/dns/Impl.cpp", definition) == []
    method = "newChannel(uri, loadInfo) {\n  return Services.io.newChannelFromURIWithLoadInfo(uri, loadInfo);\n}\n"
    assert [s.call for s in births.scan_text("browser/modules/Handler.sys.mjs", method)] == ["newChannelFromURIWithLoadInfo"]   # the call inside, not the definition
    header = "  [[nodiscard]] nsresult SpeculativeConnect(nsIURI* aURI, nsIPrincipal* aPrincipal);\n"
    assert births.scan_text("netwerk/base/Handler.h", header) == []


def test_third_party_code_and_tests_are_not_scanned():
    assert births.scan_text("third_party/lib/net.cpp", CARRIES) == []
    assert births.scan_text("netwerk/test/gtest/TestX.cpp", CARRIES) == []
    assert births.excluded_why("netwerk/base/Loader.cpp") is None


# --------------------------------------------------------------------------------------------------------------------- the judge
def test_a_tree_that_is_the_ledger_is_green():
    ledger, sites = ledger_of((FILE, CARRIES))
    report = judge(ledger, sites)
    assert (report.status, report.new, report.changed, report.gone, report.invalid) == (0, [], [], [], [])


def test_a_new_call_that_is_not_in_the_ledger_is_red():
    ledger, _ = ledger_of((FILE, CARRIES))
    sites = births.scan_text(FILE, CARRIES.replace("  return NS_OK;", "  rv = NS_NewChannel(getter_AddRefs(channel), aURI, aDoc, 1, 2);\n  return NS_OK;"))
    report = judge(ledger, sites)
    assert report.status == 1 and [s.n for s in report.new] == [2]


def test_a_new_call_in_a_new_file_is_red_and_says_what_its_text_suggests():
    ledger, _ = ledger_of((FILE, CARRIES))
    report = judge(ledger, births.scan_text(FILE, CARRIES) + births.scan_text("dom/base/Other.cpp", SYSTEM))
    assert report.status == 1 and [s.file for s in report.new] == ["dom/base/Other.cpp"]
    assert births.suggest(report.new[0])[0] == "unknown"     # the function sets attributes afterwards: read what it copies


def test_a_changed_statement_is_red():
    ledger, _ = ledger_of((FILE, CARRIES))
    changed = CARRIES.replace("aURI, aDoc,", "aURI, nsContentUtils::GetSystemPrincipal(),")
    report = judge(ledger, births.scan_text(FILE, changed))
    assert report.status == 1 and len(report.changed) == 1 and "statement" in report.changed[0][2]


def test_a_function_that_stops_setting_the_attributes_has_a_changed_context_signature_and_is_red():
    ledger, _ = ledger_of((FILE, SYSTEM), verdict="hooked", carries="no", hook="network/doh", reason="the attributes are set right after the call by the function")
    without = SYSTEM.replace("  loadInfo->SetOriginAttributes(aAttrs);\n", "")
    report = judge(ledger, births.scan_text(FILE, without), read=lambda p: "STEALTH-HOOK(network/doh)")
    assert report.status == 1 and len(report.changed) == 1 and "context signature" in report.changed[0][2]


def test_a_line_that_only_moved_is_not_red():
    ledger, _ = ledger_of((FILE, CARRIES))
    moved = "// a header comment\n// added by Mozilla\n\nint unrelated();\n" + CARRIES.replace("nsresult Loader::Open", "\n\nnsresult Loader::Open")
    sites = births.scan_text(FILE, moved)
    assert sites[0].line != births.scan_text(FILE, CARRIES)[0].line
    report = judge(ledger, sites)
    assert report.status == 0 and report.matched == 1


def test_the_same_statement_in_another_file_is_moved_and_red_until_read():
    ledger, _ = ledger_of((FILE, CARRIES))
    report = judge(ledger, births.scan_text("netwerk/base/Renamed.cpp", CARRIES))
    assert report.status == 1 and report.new == [] and len(report.moved) == 1 and report.gone == []


def test_an_entry_with_no_site_is_gone_and_not_red():
    ledger, sites = ledger_of((FILE, CARRIES), ("dom/base/Other.cpp", SYSTEM))
    report = judge(ledger, [s for s in sites if s.file == FILE])
    assert report.status == 0 and len(report.gone) == 1


# ------------------------------------------------------------------------------------------- the rule: no context and a page can reach it
def test_no_context_and_page_reachable_is_red_unless_accepted_hooked_or_dead():
    _, sites = ledger_of((FILE, SYSTEM))
    ok_but_no = {"tag": "T", "entries": [entry(sites[0], carries="no", reach="yes", verdict="ok")]}
    assert any("is ok but carries 'no'" in p for p in judge(ok_but_no, sites).invalid)
    for verdict, extra in (("accepted", {}), ("hooked", {"hook": "network/doh"}), ("dead", {"proof": "pref-off:network.x"})):
        ledger = {"tag": "T", "entries": [entry(sites[0], carries="no", reach="yes", verdict=verdict, reason="a reason that is long enough", **extra)]}
        assert judge(ledger, sites, read=lambda p: "STEALTH-HOOK(network/doh)").status == 0, verdict


def test_an_accepted_entry_needs_a_real_reason_and_a_dead_one_a_proof():
    _, sites = ledger_of((FILE, SYSTEM))
    base = dict(carries="no", reach="no")
    short = {"tag": "T", "entries": [entry(sites[0], verdict="accepted", reason="because", **base)]}
    assert any("no reason" in p for p in judge(short, sites).invalid)
    unproven = {"tag": "T", "entries": [entry(sites[0], verdict="dead", proof="trust me", **base)]}
    assert any("proof" in p for p in judge(unproven, sites).invalid)


def test_a_hook_that_a_port_lost_is_red():
    _, sites = ledger_of((FILE, SYSTEM))
    hooked = {"tag": "T", "entries": [entry(sites[0], carries="no", verdict="hooked", hook="network/doh", reason="the hook sets the attributes on the channel")]}
    assert judge(hooked, sites, read=lambda p: "STEALTH-HOOK(network/doh)").status == 0
    lost = judge(hooked, sites, read=lambda p: "nothing of ours in this file")
    assert lost.status == 1 and any("the hook is gone" in p for p in lost.invalid)
    elsewhere = {"tag": "T", "entries": [entry(sites[0], carries="no", verdict="hooked", hook="network/doh", reason="the config is made where the PeerConnection is",
                                              hook_at={"file": "dom/Other.cpp", "contains": "StealthProxyConfigOf"})]}
    texts = {"dom/Other.cpp": "STEALTH-HOOK(network/doh) auto c = StealthProxyConfigOf(x);"}
    assert judge(elsewhere, sites, read=lambda p: texts.get(p, "")).status == 0
    assert judge(elsewhere, sites, read=lambda p: "STEALTH-HOOK(network/doh)").status == 1      # the marker is gone from the other file


def test_a_hook_must_be_a_folder_of_the_series():
    _, sites = ledger_of((FILE, SYSTEM))
    ledger = {"tag": "T", "entries": [entry(sites[0], carries="no", verdict="hooked", hook="network/nowhere", reason="a hook that names no folder of SERIES")]}
    assert any("not a folder of SERIES" in p for p in judge(ledger, sites).invalid)


def test_an_open_item_is_counted_and_exits_2_and_a_new_site_beside_it_exits_1():
    _, sites = ledger_of((FILE, SYSTEM))
    opened = {"tag": "T", "entries": [entry(sites[0], carries="no", verdict="fix", reason="a request a page causes leaves in context 0",
                                           open={"since": "2026-11-13", "item": "the hash completer", "owner": "pm"})]}
    report = judge(opened, sites)
    assert (report.status, len(report.open), report.red) == (2, 1, False)
    both = judge(opened, sites + births.scan_text("dom/base/Other.cpp", CARRIES))
    assert (both.status, len(both.open), len(both.new)) == (1, 1, 1)


def test_a_fix_with_no_dated_open_state_is_invalid():
    _, sites = ledger_of((FILE, SYSTEM))
    for opened in (None, {"item": "x"}, {"since": "yesterday", "item": "x"}):
        entry_ = entry(sites[0], carries="no", verdict="fix", reason="a request a page causes leaves in context 0")
        if opened is not None:
            entry_["open"] = opened
        assert any("dated open state" in p for p in judge({"tag": "T", "entries": [entry_]}, sites).invalid), opened


# ------------------------------------------------------------------------------------------------------------------ the false friend
HTTPS_ONLY = """\
nsresult Racer::Start(nsIChannel* aOrig, nsIURI* aURI) {
  nsCOMPtr<nsILoadInfo> origLoadInfo = aOrig->LoadInfo();
  mozilla::OriginAttributes attrs = origLoadInfo->GetOriginAttributes();
  RefPtr<nsIPrincipal> nullPrincipal = mozilla::NullPrincipal::Create(attrs);
  nsCOMPtr<nsIChannel> testHTTPChannel;
  nsresult rv = NS_NewChannel(getter_AddRefs(testHTTPChannel), aURI,
                              nullPrincipal,
                              nsILoadInfo::SEC_ALLOW_CROSS_ORIGIN_SEC_CONTEXT_IS_NULL,
                              nsIContentPolicy::TYPE_OTHER);
  return rv;
}
"""
EXPAT = """\
nsresult Driver::Open(nsIURI* uri) {
  nsCOMPtr<nsIPrincipal> nullPrincipal = mozilla::NullPrincipal::CreateWithoutOriginAttributes();
  nsresult rv = NS_NewChannel(getter_AddRefs(channel), uri, nullPrincipal, flags, policyType);
  return rv;
}
"""


def test_a_null_principal_made_from_attributes_is_not_flagged_and_one_made_without_them_is():
    friend = births.scan_text("dom/security/nsHTTPSOnlyUtils.cpp", HTTPS_ONLY)[0]
    assert births.suggest(friend)[0] == "yes" and "NullPrincipal::Create(attrs)" in births.suggest(friend)[1]
    bare = births.scan_text("parser/htmlparser/nsExpatDriver.cpp", EXPAT)[0]
    assert births.suggest(bare)[0] == "no" and "without attributes" in births.suggest(bare)[1]
    system = births.scan_text("dom/base/Other.cpp", SYSTEM.replace("  loadInfo->SetOriginAttributes(aAttrs);\n", ""))[0]
    assert births.suggest(system)[0] == "no"
    # And the skeleton of a NEW site starts from that suggestion, never from "ok": its verdict is "review", which the ledger refuses.
    skeleton = births.skeleton([friend])[0]
    assert skeleton["verdict"] == "review" and skeleton["carries"] == "yes"
    assert births.ledger_problems({"entries": [dict(skeleton, reason="x" * 30)]})


# ------------------------------------------------------------------------------------------------------------------- the ledger file
def _entries(*kw):
    base = dict(file="a.cpp", function="f", kind="channel", call="NS_NewChannel", n=1, stmt_sha="0", ctx_sig="", carries="yes", reach="yes",
                verdict="ok", reason="a reason that is long enough")
    return {"entries": [dict(base, **k) for k in kw]}


def test_the_ledger_must_be_sorted_unique_and_complete():
    assert births.ledger_problems(_entries({}, {"file": "b.cpp"})) == []
    assert any("out of order" in p for p in births.ledger_problems(_entries({"file": "b.cpp"}, {})))
    assert any("listed twice" in p for p in births.ledger_problems(_entries({}, {})))
    incomplete = _entries({})
    del incomplete["entries"][0]["stmt_sha"]
    assert any("no 'stmt_sha'" in p for p in births.ledger_problems(incomplete))
    assert any("verdict" in p for p in births.ledger_problems(_entries({"verdict": "review"})))
    assert any("it is ok" in p for p in births.ledger_problems(_entries({"verdict": "accepted"})))


def test_an_open_state_belongs_to_a_fix_only():
    assert any("open state but its verdict" in p for p in births.ledger_problems(_entries({"open": {"since": "2026-11-13", "item": "x"}})))


def test_the_chrome_js_http_clients_may_not_grow_unnoticed():
    assert births.judge_chrome_js({"chrome_js_http": {"toolkit/components": 110}}, {"toolkit/components": 110}) == []
    said = births.judge_chrome_js({"chrome_js_http": {"toolkit/components": 110}}, {"toolkit/components": 111, "browser/modules": 1})
    assert len(said) == 2 and "toolkit/components: 111" in said[0] or "toolkit/components: 111" in said[1]


def test_the_ledger_of_the_series_is_valid_against_its_series():
    assert births.ledger_problems(births.load_ledger(), set(births.series_folder_list())) == []


def test_the_hash_completer_and_the_profile_lock_are_hooked_not_open_nor_accepted():
    by_file = {e["file"]: e for e in births.load_ledger()["entries"]}
    for name in ("toolkit/components/url-classifier/UrlClassifierHashCompleter.sys.mjs", "toolkit/profile/nsProfileLock.cpp"):
        assert by_file[name]["verdict"] == "hooked" and by_file[name]["hook"] == "network/doh"
    assert [e for e in births.load_ledger()["entries"] if e["verdict"] == "fix"] == []


# ------------------------------------------------------------------------------------------------------- a repository, and a commit of it
def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "netwerk" / "base").mkdir(parents=True)
    (tmp_path / FILE).write_text(CARRIES, encoding="utf-8")
    (tmp_path / "third_party").mkdir()
    (tmp_path / "third_party" / "x.cpp").write_text(CARRIES, encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "one")
    return tmp_path


def test_a_tree_on_disk_and_a_commit_of_it_give_the_same_sites(repo):
    on_disk = births.scan(births.Source(repo))
    at_head = births.scan(births.Source(repo, "HEAD"))
    assert [s.key for s in on_disk] == [s.key for s in at_head] == [(FILE, "Loader::Open", "channel", "NS_NewChannel", 1)]
    assert on_disk[0].stmt_sha == at_head[0].stmt_sha


def test_run_gives_status_0_on_the_ledger_and_1_on_a_new_call(repo, tmp_path, capsys):
    ledger, _ = ledger_of((FILE, CARRIES))
    path = tmp_path / "ledger.json"
    births.save_ledger(ledger, path)
    assert births.run(births.Source(repo), ["network/doh"], path) == 0
    (repo / "dom").mkdir()
    (repo / "dom" / "New.cpp").write_text(SYSTEM, encoding="utf-8")
    assert births.run(births.Source(repo), ["network/doh"], path) == 1
    out = capsys.readouterr().out
    assert "NEW      dom/New.cpp" in out and "NEW 1" in out and "RED" in out
    json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------------------------------------ the wiring
def test_the_scan_is_a_step_of_the_checks_workflow_right_after_the_materialize_step():
    text = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "checks.yml").read_text(encoding="utf-8")
    materialize = text.index("engine.py materialize --into source")
    step = text.index("python .series/tools/births.py --tree source")
    assert materialize < step < text.index("repository: oss-invisible/core")
    assert text[:step].count("- name:") - text[:materialize].count("- name:") == 1       # the step that follows the materialize step


def test_a_port_ends_with_the_scan_of_the_commit_it_made_and_fails_on_a_new_or_changed_site():
    import inspect

    import engine
    source = inspect.getsource(engine.port)
    assert "births.run(reader" in source and "status == 1" in source and "check_births" in source
    assert source.index("update-ref") < source.index("births.run(")
    assert "check_births=True" in inspect.getsource(engine.main)          # the command line port scans; the library call of a test does not


def test_only_a_firefox_tree_is_scanned_at_the_end_of_a_port(repo):
    assert births.Source(repo).is_firefox_tree() is False and births.Source(repo, "HEAD").is_firefox_tree() is False
    (repo / "netwerk" / "base" / "nsSocketTransportService2.cpp").write_text("// the network stack" + chr(10), encoding="utf-8")
    assert births.Source(repo).is_firefox_tree() is True
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "two")
    assert births.Source(repo, "HEAD").is_firefox_tree() is True


def test_the_check_of_the_series_reads_the_ledger():
    import engine
    assert "births.ledger_problems" in inspect_source(engine.problems)


def inspect_source(fn):
    import inspect
    return inspect.getsource(fn)
