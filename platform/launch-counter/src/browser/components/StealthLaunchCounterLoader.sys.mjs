/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The loader of the launch counter, called by the one line of BrowserGlue._beforeUIStartup. It imports nothing at the top, so a
// defect of the counter module (a file missing from the package, a syntax error) cannot stop it from loading: the guarded
// import of the counter is inside fire(), and a failure of any kind (the module does not load, or its fire() throws) stops here,
// so it never skips what BrowserGlue does after the line (SessionStartup.init()). The counter is mandatory, so the failure is
// logged, loudly, the way the other modules of ours log what must not be missed (console.error).

export const StealthLaunchCounterLoader = {
  fire() {
    try {
      ChromeUtils.importESModule(
        "resource:///modules/StealthLaunchCounter.sys.mjs"
      ).StealthLaunchCounter.fire();
    } catch (e) {
      console.error("The anonymous launch counter could not be started:", e);
    }
  },
};
