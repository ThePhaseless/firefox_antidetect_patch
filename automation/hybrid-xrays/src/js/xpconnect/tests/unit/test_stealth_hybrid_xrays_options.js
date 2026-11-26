/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

// STEALTHFOX [B322]: the `hybridXrays` option of Cu.Sandbox, the caller's world
// of Juggler (the rule is written in js/xpconnect/wrappers/StealthHybridXray.h).
// The option needs a content principal and `wantXrays: false`; any other
// combination is refused, and the same calls without the option work: the
// refusal is the option's, not the principal's or wantXrays'.

const CONTENT = "http://example.com/";

function refused(aFn) {
  try {
    aFn();
  } catch (e) {
    return true;
  }
  return false;
}

function run_test() {
  const system = Services.scriptSecurityManager.getSystemPrincipal();
  const expanded = [CONTENT, "http://example.org/"];

  // The caller's world: a content principal, `wantXrays: false`.
  const hybrid = Cu.Sandbox(CONTENT, { wantXrays: false, hybridXrays: true });
  Assert.equal(Cu.evalInSandbox("1 + 1", hybrid), 2, "a hybrid sandbox runs");

  // Refused: the system principal, an expanded principal, `wantXrays: true`
  // (the default, so also an option left out), a value that is not a boolean.
  Assert.ok(
    refused(() => Cu.Sandbox(system, { wantXrays: false, hybridXrays: true })),
    "the system principal is refused"
  );
  Assert.ok(
    refused(() => Cu.Sandbox(expanded, { wantXrays: false, hybridXrays: true })),
    "an expanded principal is refused"
  );
  Assert.ok(
    refused(() => Cu.Sandbox(CONTENT, { wantXrays: true, hybridXrays: true })),
    "wantXrays: true is refused"
  );
  Assert.ok(
    refused(() => Cu.Sandbox(CONTENT, { hybridXrays: true })),
    "wantXrays left at its default (true) is refused"
  );
  Assert.ok(
    refused(() => Cu.Sandbox(CONTENT, { wantXrays: false, hybridXrays: "x" })),
    "a value that is not a boolean is refused"
  );

  // The option is read right after `wantXrays`, so with two values that are not
  // booleans the error names the first (the order of the reads of Parse's
  // chain), and a bad `wantXrays` alone is refused before `hybridXrays` is read.
  const errorOf = aOptions => {
    try {
      Cu.Sandbox(CONTENT, aOptions);
    } catch (e) {
      return String(e.message || e);
    }
    return "";
  };
  Assert.ok(
    errorOf({ wantXrays: "x", hybridXrays: "y" }).includes("wantXrays"),
    "two bad values: the error is the one of wantXrays"
  );
  Assert.ok(
    !errorOf({ wantXrays: "x", hybridXrays: "y" }).includes("hybridXrays"),
    "two bad values: hybridXrays was not read"
  );
  Assert.ok(
    errorOf({ wantXrays: false, hybridXrays: "y" }).includes("hybridXrays"),
    "a bad hybridXrays alone names hybridXrays"
  );

  // Control: the same calls without the option work.
  Cu.Sandbox(system, { wantXrays: false });
  Cu.Sandbox(expanded, { wantXrays: false });
  Cu.Sandbox(CONTENT, { wantXrays: true });
  Cu.Sandbox(CONTENT, {});
  Cu.Sandbox(CONTENT, { wantXrays: false, hybridXrays: false });
}
