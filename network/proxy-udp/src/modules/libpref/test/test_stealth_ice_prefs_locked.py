# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""The two prefs that decide WHERE a PeerConnection's ICE runs are locked to the retail value, once, at startup.

The SOCKS5 UDP layer is attached in one place, NrSocket::create, in the process that owns nICEr's sockets: the socket process in a
retail build. media.peerconnection.mtransport_process=false (ICE in the content process) and network.process.enabled=false (no socket
process) put the sockets in classes with no layer. Behind a proxy a client that set either would run an ICE with no relay: no srflx, no
relay candidate, and nothing proves it cannot send direct. They are therefore locked after the user prefs are loaded: a locked pref
reads its default whatever user.js, prefs.js or a caller wrote.

The lock is StealthLockIcePrefs (toolkit/xre/StealthIcePrefs.cpp), called by XREMain::XRE_mainRun (toolkit/xre/nsAppRunner.cpp) right
after mDirProvider.InitializeUserPrefs(). Both prefs are declared by Mozilla and we do not change their value, so there is nothing to
declare here: this test asserts the ONLY ENTRY, so a second place that locks or sets them, or a call that moves before the load of the
user prefs, is seen: the one function that locks, locks both, once; the one call of it is after the load; nobody declares them again.

Run: python modules/libpref/test/test_stealth_ice_prefs_locked.py
"""

import os
import re
import sys

TREE = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
APPRUNNER = "toolkit/xre/nsAppRunner.cpp"
OWN = "toolkit/xre/StealthIcePrefs.cpp"
PREFS = ["network.process.enabled", "media.peerconnection.mtransport_process"]


def source(rel):
    with open(os.path.join(TREE, rel), encoding="utf-8") as f:
        return f.read()


def test_the_function_locks_both_prefs_once():
    text = source(OWN)
    body = text[text.index("void StealthLockIcePrefs() {"):]
    body = body[:body.index("\n}\n")]
    for name in PREFS:
        locks = re.findall(r'Preferences::Lock\(\s*"%s"\s*\)' % re.escape(name), body)
        assert len(locks) == 1, "%s must be locked exactly once in StealthLockIcePrefs, found %d" % (name, len(locks))
        assert not re.search(r'Preferences::(Set|Clear)\w*\(\s*"%s"' % re.escape(name), text), "%s is also written in %s" % (name, OWN)


def test_the_only_call_is_right_after_the_user_prefs_are_loaded():
    text = source(APPRUNNER)
    calls = [m.start() for m in re.finditer(r"StealthLockIcePrefs\(\);", text)]
    assert len(calls) == 1, "StealthLockIcePrefs must be called exactly once in %s, found %d" % (APPRUNNER, len(calls))
    load = text.index("mDirProvider.InitializeUserPrefs();")
    assert calls[0] > load, "the prefs are locked before the user prefs are loaded: a user value set later would not be seen as locked"
    assert calls[0] - load < 200, "the prefs are locked far from the load of the user prefs"
    # The only entry: Mozilla's file does not lock them itself any more.
    for name in PREFS:
        assert name not in text, "%s is named in %s: a second place that decides it" % (name, APPRUNNER)


def test_nobody_declares_them_again():
    # Declared by Mozilla; a second declaration of ours would win by load order and hide the retail value (see
    # test_stealth_prefs_declared_once.py).
    for rel in ["modules/libpref/init/StealthPrefs.js", "modules/libpref/init/StealthPrefList.yaml"]:
        text = source(rel)
        for name in PREFS:
            assert name not in text, "%s declares %s" % (rel, name)


if __name__ == "__main__":
    failed = 0
    for fn in [test_the_function_locks_both_prefs_once, test_the_only_call_is_right_after_the_user_prefs_are_loaded,
               test_nobody_declares_them_again]:
        try:
            fn()
            print("ok   ", fn.__name__)
        except AssertionError as e:
            failed += 1
            print("FAIL ", fn.__name__, "-", e)
    sys.exit(1 if failed else 0)
