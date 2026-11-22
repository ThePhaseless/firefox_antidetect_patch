# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""The final value of the Mozilla prefs we change on Mozilla's own lines.

Reads the pref files in the order the browser loads them (greprefs.js: all.js
then StealthPrefs.js; then browser/app/profile/firefox.js), preprocesses their
#if blocks for a Linux and a Windows build, and takes the last declaration of
each pref. The control is the same reader on the lines Mozilla ships: it must
give the values of stock Firefox, so a hook that stops changing a value turns
this test red.

The load order is taken from greprefs.js itself (its #include lines), so a
greprefs.js that no longer includes StealthPrefs.js loses our defaults here.
moz.build is read the way the build reads it: the top-level pref_groups and
gen_inputs lists, to see that the generator gets our static prefs.

Run: python modules/libpref/test/test_stealth_prefs_final_values.py
"""

import ast
import os
import re
import sys

TREE = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
GREPREFS = "modules/libpref/greprefs.js"
FIREFOX_JS = "browser/app/profile/firefox.js"
MOZ_BUILD = "modules/libpref/moz.build"
OUR_YAML = "modules/libpref/init/StealthPrefList.yaml"
LINUX = {"XP_UNIX", "MOZ_WIDGET_GTK"}
WINDOWS = {"XP_WIN"}

TRANSLATIONS = ["browser.translations.enable", "browser.translations.select.enable"]
MONOSPACE = [
    "font.size.monospace." + s
    for s in ("ar", "el", "he", "x-cyrillic", "x-unicode", "x-western")
]

PREF = re.compile(r'^\s*(?:pref|sticky_pref)\(\s*"([^"]+)"\s*,\s*([^)]*?)\s*\)\s*;')
DEFINED = re.compile(r"defined\(\s*(\w+)\s*\)")
NOT_EQUAL = re.compile(r"(\w+)\s*!=\s*(\w+)")


def evaluate(expr, defines):
    expr = expr.strip()
    expr = DEFINED.sub(lambda m: "(%r in D)" % m.group(1), expr)
    expr = NOT_EQUAL.sub(lambda m: "(V.get(%r) != %r)" % (m.group(1), m.group(2)), expr)
    expr = expr.replace("&&", " and ").replace("||", " or ")
    expr = re.sub(r"!(?!=)", " not ", expr)
    return bool(eval(expr, {"__builtins__": {}}, {"D": defines, "V": {"MOZ_UPDATE_CHANNEL": "release"}}))


def declarations(text, defines):
    """Yield (name, raw value) of the pref() lines that survive the #if blocks."""
    stack = []  # per block: [active before, a branch already taken, this branch live]
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            d = s[1:].strip()
            outer = all(f[2] for f in stack)
            if d.startswith("ifdef "):
                v = d[6:].strip() in defines
                stack.append([outer, v, v])
            elif d.startswith("ifndef "):
                v = d[7:].strip() not in defines
                stack.append([outer, v, v])
            elif d.startswith("if "):
                v = evaluate(d[3:], defines)
                stack.append([outer, v, v])
            elif d.startswith("elif "):
                f = stack[-1]
                v = (not f[1]) and evaluate(d[5:], defines)
                f[1] = f[1] or v
                f[2] = v
            elif d.split()[:1] == ["else"]:
                f = stack[-1]
                f[2] = not f[1]
                f[1] = True
            elif d.split()[:1] == ["endif"]:
                stack.pop()
            continue
        if all(f[2] for f in stack):
            m = PREF.match(line)
            if m:
                yield m.group(1), m.group(2)
    assert not stack, "unbalanced #if"


def final_values(texts, defines):
    out = {}
    for text in texts:
        for name, value in declarations(text, defines):
            out[name] = value
    return out


def read(rel):
    with open(os.path.join(TREE, rel), encoding="utf-8") as f:
        return f.read()


def load_order(greprefs_text):
    """The texts in the order the browser loads them: what greprefs.js
    includes, then the application's firefox.js."""
    includes = re.findall(r"^#include\s+(\S+)", greprefs_text, re.M)
    return [read("modules/libpref/" + i) for i in includes] + [read(FIREFOX_JS)]


def tree_texts():
    return load_order(read(GREPREFS))


def lists(build_text):
    """The string items of the top-level pref_groups and gen_inputs lists."""
    out = {"pref_groups": set(), "gen_inputs": set()}
    for node in ast.parse(build_text).body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        else:
            continue
        for name in names:
            if name in out and isinstance(node.value, ast.List):
                out[name] |= {e.value for e in node.value.elts if isinstance(e, ast.Constant)}
    return out


# The lines Mozilla ships in Firefox 159, for the control.
MOZILLA_ALL_JS = """\
pref("browser.translations.enable", false);
pref("browser.translations.select.enable", false);
pref("font.size.monospace.x-math", 13);
#if !defined(ANDROID) && !defined(XP_MACOSX) && defined(XP_UNIX)
  pref("font.size.monospace.ar", 12);
  pref("font.size.monospace.el", 12);
  pref("font.size.monospace.he", 12);
  pref("font.size.monospace.x-cyrillic", 12);
  pref("font.size.monospace.x-unicode", 12);
  pref("font.size.monospace.x-western", 12);
#endif
"""
MOZILLA_FIREFOX_JS = """\
pref("browser.translations.enable", true);
pref("browser.translations.select.enable", true);
"""
MOZILLA_GLOBAL_MONOSPACE = "".join('pref("%s", 13);\n' % n for n in MONOSPACE)


def test_the_reader_reproduces_stock_firefox():
    # Control: on Mozilla's own lines translations are on (firefox.js wins over
    # all.js) and the desktop Unix monospace sizes are 12.
    stock = [MOZILLA_GLOBAL_MONOSPACE + MOZILLA_ALL_JS, MOZILLA_FIREFOX_JS]
    linux = final_values(stock, LINUX)
    assert linux["browser.translations.enable"] == "true"
    assert linux["browser.translations.select.enable"] == "true"
    assert [linux[n] for n in MONOSPACE] == ["12"] * 6
    windows = final_values(stock, WINDOWS)
    assert [windows[n] for n in MONOSPACE] == ["13"] * 6


def test_translations_are_off_in_the_load_order():
    for defines in (LINUX, WINDOWS):
        values = final_values(tree_texts(), defines)
        for name in TRANSLATIONS:
            assert values[name] == "false", "%s is %s" % (name, values[name])


def test_monospace_sizes_are_13_on_linux_and_windows():
    for defines in (LINUX, WINDOWS):
        values = final_values(tree_texts(), defines)
        for name in MONOSPACE:
            assert values[name] == "13", "%s is %s" % (name, values[name])


def test_our_defaults_reach_the_load_order_through_greprefs():
    values = final_values(tree_texts(), LINUX)
    assert values["ui.font.caption"] == '"Segoe UI"'
    # Control: greprefs.js without the include of StealthPrefs.js loses them.
    without = "".join(
        l for l in read(GREPREFS).splitlines(True) if "StealthPrefs.js" not in l
    )
    assert "ui.font.caption" not in final_values(load_order(without), LINUX)


def test_the_generator_gets_our_pref_list_and_groups():
    groups = {
        m.group(1)
        for m in re.finditer(r"^- name:\s*([^.\s]+)\.", read(OUR_YAML), re.M)
    }
    assert "juggler" in groups and "zoom" in groups, "our yaml not read"
    ours = lists(read(MOZ_BUILD))
    assert groups <= ours["pref_groups"], groups - ours["pref_groups"]
    assert "init/StealthPrefList.yaml" in ours["gen_inputs"]
    # Control: without our two lines the generator would not know them.
    without = "".join(
        l for l in read(MOZ_BUILD).splitlines(True) if "STEALTH-HOOK" not in l
    )
    bare = lists(without)
    assert "juggler" not in bare["pref_groups"]
    assert "init/StealthPrefList.yaml" not in bare["gen_inputs"]


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print("ok  ", name)
            except AssertionError as e:
                failed += 1; print("FAIL", name, e)
    sys.exit(1 if failed else 0)
