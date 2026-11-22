/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The mode "generate" quits right after profile-after-change, before the browser
// has a window. Firefox starts Glean at browser-idle-startup, which never comes
// there, so by default Glean would be initialised inside the shutdown
// (toolkit/components/glean/xpcom/FOG.cpp reads telemetry.fog.init_on_shutdown at
// XPCOMShutdown) and race Mozilla's own close_db: a panic and a SIGSEGV on about
// 2 launches in 12. runAndQuit declares the pref false, on the default branch and
// as its very first step, so that Glean is never started by the shutdown.

"use strict";

const PREF_INIT_ON_SHUTDOWN = "telemetry.fog.init_on_shutdown";

const { StealthSecurityState } = ChromeUtils.importESModule(
  "resource://gre/modules/psm/StealthSecurityState.sys.mjs"
);

add_task(async function test_run_and_quit_declares_glean_not_started_at_shutdown() {
  // A profile: run() of the mode writes its marker there.
  do_get_profile();

  const defaults = Services.prefs.getDefaultBranch(null);
  // Negative control: Mozilla's value is true; without the mode nothing sets it
  // false (a test that starts from false proves nothing).
  Assert.ok(
    defaults.getBoolPref(PREF_INIT_ON_SHUTDOWN),
    "Mozilla's default is true before the mode runs"
  );
  Assert.ok(
    !Services.prefs.prefHasUserValue(PREF_INIT_ON_SHUTDOWN),
    "no user value before the mode runs"
  );

  // The generation itself is not what is tested here: it is stubbed, so the test
  // does not touch cert_storage or the network.
  const realRun = StealthSecurityState.run;
  StealthSecurityState.run = async () => 0;
  registerCleanupFunction(() => {
    StealthSecurityState.run = realRun;
  });

  // An application of the test's own. The pref is read at the very first call the
  // mode makes on it, which is before anything else of the mode has run.
  const calls = [];
  let atEnter = null;
  const startup = {
    enterLastWindowClosingSurvivalArea() {
      atEnter = defaults.getBoolPref(PREF_INIT_ON_SHUTDOWN);
      calls.push("enter");
    },
    exitLastWindowClosingSurvivalArea: () => calls.push("exit"),
    quit: (mode, status) => calls.push("quit " + mode + " " + status),
  };

  const status = await StealthSecurityState.runAndQuit(startup);

  Assert.equal(status, 0, "the mode answers with the generation's status");
  Assert.equal(
    calls.join(", "),
    "enter, quit " + Ci.nsIAppStartup.eForceQuit + " 0, exit",
    "the mode held the application, quit it and left"
  );
  Assert.strictEqual(
    atEnter,
    false,
    "Glean is declared not started at shutdown before the application is held open"
  );
  Assert.strictEqual(
    Services.prefs.getBoolPref(PREF_INIT_ON_SHUTDOWN),
    false,
    "the effective value FOG.cpp reads at XPCOMShutdown is false"
  );
  Assert.ok(
    !Services.prefs.prefHasUserValue(PREF_INIT_ON_SHUTDOWN),
    "it is declared on the default branch: nothing is written to the user branch (prefs.js)"
  );
});
