// The persona is a Windows machine whose system location is declared ON. Firefox
// asked the OS: GetGeolocationPermissionBehavior (GeolocationSystemWin.cpp) reads
// the privacy switch through AppCapability("location").CheckAccess() on every
// request (capabilityaccessmanagerclient.dll is loaded in the parent for it), and
// with the OS switch off the request was cancelled with PERMISSION_DENIED
// (Geolocation.cpp nsGeolocationRequest::Allow, while
// dom.geolocation.require_system_permission.enabled is true). A page must see the
// declared answer, not the switch of the machine the browser runs on.
//
// The answer is given where Firefox reads the host: the first statement of
// GetGeolocationPermissionBehavior returns NoPrompt (the behavior the generic
// GeolocationSystem.cpp already has on Linux) before any AppCapability call, and
// Mozilla's body stays intact below it. The OS is read a second time, by the
// monitor navigator.permissions.query starts in the parent
// (PermissionObserver::EnsureMonitoringInParent -> the Windows permission monitor,
// AppCapability::Create + an access-changed subscription, which is what loads
// capabilityaccessmanagerclient.dll after the query): with the switch declared on
// it never changes, so the monitor is not started. The acceptance contract for the
// end-to-end is at the top of geolocation_windows_provider_never_selected.test.mjs.
//
// Run: node --test juggler/tests/*.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const TREE = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const read = rel => fs.readFileSync(path.join(TREE, rel), 'utf8');
const WIN = 'dom/geolocation/GeolocationSystemWin.cpp';
const FOLDER = 'fingerprint/geolocation/no-host-provider';

const win = read(WIN);
const fn = win.slice(win.indexOf('SystemGeolocationPermissionBehavior GetGeolocationPermissionBehavior() {'),
  win.indexOf('already_AddRefed<SystemGeolocationPermissionRequest>\nRequestLocationPermissionFromUser'));

test('GetGeolocationPermissionBehavior is the only OS read of the switch on the request path, and our guard precedes it', () => {
  // The calls of GetLocationAccess() with no argument (it creates the AppCapability): this function and the
  // prompt path RequestLocationPermissionFromUser, reached only for a behavior other than NoPrompt (below).
  const calls = win.split('\n').flatMap((l, n) => /GetLocationAccess\(\)/.test(l) && !/^Maybe<|^\s*\/\//.test(l) ? [n] : []);
  assert.equal(calls.length, 2, 'one use in the behavior, one in the prompt path');
  const body = fn.slice(0, fn.indexOf('\n}\n'));
  assert.equal(body.split('GetLocationAccess()').length, 2);
  const guard = body.indexOf('StealthSystemLocationDeclaredOn()');
  assert.ok(guard > 0);
  assert.ok(guard < body.indexOf('GetLocationAccess()'));
  assert.ok(body.slice(0, guard).split('\n').every(l => !/;\s*$/.test(l)), 'no statement of Mozilla before the guard');
  const prompt = win.slice(win.indexOf('RequestLocationPermissionFromUser'));
  assert.equal(prompt.split('GetLocationAccess()').length, 2);
});

test("Mozilla's body of the function is intact below the hook (no line of Mozilla removed)", () => {
  assert.ok(fn.includes(
    '  auto locationAccess = GetLocationAccess();\n' +
    '  if (SystemWillPromptForPermissionHint(locationAccess)) {\n' +
    '    return SystemGeolocationPermissionBehavior::SystemWillPromptUser;\n' +
    '  }\n' +
    '  if (!LocationIsPermittedHint(locationAccess)) {\n' +
    '    return SystemGeolocationPermissionBehavior::GeckoWillPromptUser;\n' +
    '  }\n' +
    '  return SystemGeolocationPermissionBehavior::NoPrompt;\n' +
    '}\n'));
});

test('the declaration is one pure function of our own file, with no OS call', () => {
  const cpp = read('toolkit/components/geolocation/StealthGeolocation.cpp');
  const header = read('toolkit/components/geolocation/StealthGeolocation.h');
  assert.match(header, /bool StealthSystemLocationDeclaredOn\(\);/);
  assert.match(cpp, /bool StealthSystemLocationDeclaredOn\(\) \{\s*return true;\s*\}/);
  assert.doesNotMatch(cpp, /AppCapability|CheckAccess|GetLocationAccess|XP_WIN/);
});

test('AppCapability is read in three places only: the function above, the monitor of the hook below, and a comment', () => {
  const out = execFileSync('git', ['grep', '-lE', 'AppCapability|capabilityaccessmanager',
    '--', '*.cpp', '*.h', '*.mm', '*.rs', ':!third_party/*', ':!build/*', ':!toolkit/components/geolocation/*'],
  { cwd: TREE, encoding: 'utf8' });
  assert.deepEqual(out.trim().split('\n'), [
    WIN,
    'dom/permission/PermissionObserver.cpp',   // a comment; the monitor is started by the Rust component below
    'widget/windows/rust/src/permission_monitor.rs',
  ]);
  // RequestLocationPermissionFromUser (which reads the OS again) is called only for a behavior other than NoPrompt.
  const geo = read('dom/geolocation/Geolocation.cpp');
  assert.ok(geo.includes('if (mBehavior != SystemGeolocationPermissionBehavior::NoPrompt) {'));
  assert.ok(geo.includes('case geolocation::SystemGeolocationPermissionBehavior::NoPrompt:'));
});

test('the OS monitor of a permission is created in one place, reached from one caller, and our guard precedes it', () => {
  const rel = 'dom/permission/PermissionObserver.cpp';
  const obs = read(rel);
  const entry = obs.slice(obs.indexOf('void PermissionObserver::EnsureMonitoringInParent('));
  const body = entry.slice(0, entry.indexOf('\n}\n'));
  assert.ok(body.indexOf('StealthSkipsPermissionMonitor(aName)') > 0);
  assert.ok(body.indexOf('StealthSkipsPermissionMonitor(aName)') < body.indexOf('EnsureOSMonitoring(aName)'));
  // EnsureOSMonitoring is called only from this entry, and the monitor contract is created only inside it.
  assert.equal(obs.split('EnsureOSMonitoring(').length, 3, 'its definition and the one call');
  assert.equal(obs.split('@mozilla.org/permission-monitor;1').length, 2);
  // The one caller of the entry, and the one place that creates the monitor.
  const out = execFileSync('git', ['grep', '-nE', 'EnsureMonitoringInParent|permission-monitor;1', '--', '*.cpp', '*.h', '*.mm'],
    { cwd: TREE, encoding: 'utf8' });
  assert.deepEqual(out.trim().split('\n').map(l => l.split(':')[0]).sort(), [
    'dom/ipc/ContentParent.cpp', rel, rel, 'dom/permission/PermissionObserver.h',
  ].sort());
});

test("the gtest row is in the suite the candidate's filter runs (StealthDeclaredNetwork)", () => {
  const gtest = read('toolkit/components/geolocation/test/gtest/TestStealthGeolocation.cpp');
  assert.match(gtest, /TEST\(StealthDeclaredNetwork, TheSystemLocationSwitchIsDeclaredOn\)/);
  assert.match(gtest, /EXPECT_TRUE\(mozilla::StealthSystemLocationDeclaredOn\(\)\)/);
});
