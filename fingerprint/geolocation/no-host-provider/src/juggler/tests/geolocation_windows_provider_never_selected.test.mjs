// The persona's location comes ONLY from the core's declaration (the geolocation
// override sent by Browser.setGeolocationOverride). The engine never reads the
// host for a position. The Windows location provider (WindowsLocationProvider and
// the actors of the WINDOWS_UTILS utility process: geolocation.dll,
// locationframeworkps.dll) is in the tree exactly as Mozilla wrote it, and cannot
// be reached: GeolocationService::Init() returns below our guard before the only
// `new WindowsLocationProvider()`, and the provider is the only caller of
// UtilityProcessManager::GetWindowsUtilsPromise, the only way the process starts.
// The hook StealthSelectGeolocationProvider keeps every host provider out (Windows,
// Linux Portal and GeoClue, macOS CoreLocation, Android). A watchPosition reaches
// the PARENT's global service even with an override (Geolocation.cpp StartDevice ->
// AddGeolocationListener -> ContentParent.cpp RecvAddGeolocationListener).
//
// ACCEPTANCE CONTRACT for the end-to-end of the whole family (hooks A, B, C, D;
// the e2e itself is another agent's). Browser with a declared geolocation override
// (Browser.setGeolocationOverride, made-up 45.0 / 9.0 / accuracy 1500), headless,
// permission granted for the probe origin, then on the page, in this order:
// navigator.permissions.query({name:'geolocation'}), getCurrentPosition, and
// watchPosition left running 10 s (first callback, then clearWatch).
//   1. Page-visible: permission state 'granted'; getCurrentPosition and the first
//      watchPosition callback give coords 45.0 / 9.0, accuracy 1500, altitude,
//      altitudeAccuracy, heading, speed null; the watch gets exactly one callback
//      and no error (not code 1 PERMISSION_DENIED, not code 2).
//   2. Page-visible (hook D): in every callback position.timestamp - Date.now(),
//      with Date.now() read right after the timestamp, is between -2 and 0 ms
//      (never +86,400,000 ms, never growing positive); two reads of the timestamp
//      of the same position taken 50 ms apart differ by about 50 ms.
//   3. Host-visible, for every firefox.exe of the process tree (parent, content,
//      utility, socket, GPU...), module BASE NAMES ever loaded, sampled after each
//      of the three steps and 2 s after the last: geolocation.dll,
//      locationframeworkps.dll, wlanapi.dll and capabilityaccessmanagerclient.dll
//      are all ABSENT (case-insensitive).
//   4. Host-visible: no process of the tree has the command line option
//      -sandboxingKind 3 (WINDOWS_UTILS); 0 (GENERIC_UTILITY) may exist.
//   5. Control: the same run on the previous candidate (before these hooks) shows
//      geolocation.dll + locationframeworkps.dll + a -sandboxingKind 3 process
//      after watchPosition, and capabilityaccessmanagerclient.dll after the
//      permission query; the e2e must fail on it and pass on this build.
//   6. Without an override (declared position absent), same run: getCurrentPosition
//      and watchPosition both answer POSITION_UNAVAILABLE (code 2, message
//      "Unknown error acquiring position") within about 100 ms, and items 3 and 4
//      hold as well.
//
// This file pins THE ONLY ENTRY of the host providers (a second entry that Mozilla
// adds in a later version fails it); B, C and D have their own tests.
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
const SERVICE = 'toolkit/components/geolocation/GeolocationService.cpp';
const OWN_CPP = 'toolkit/components/geolocation/StealthGeolocation.cpp';
const OWN_H = 'toolkit/components/geolocation/StealthGeolocation.h';
const FOLDER = 'fingerprint/geolocation/no-host-provider';

const service = read(SERVICE);
const init = service.slice(service.indexOf('nsresult GeolocationService::Init()'),
  service.indexOf('GeolocationService::~GeolocationService()'));

const gitGrep = args => {
  try {
    return execFileSync('git', ['grep', ...args], { cwd: TREE, encoding: 'utf8' });
  } catch (e) {
    if (e.status === 1) return '';
    throw e;
  }
};
const lines = out => out.trim().split('\n').filter(Boolean);

test('the hook runs after the shutdown observer and before every provider Mozilla selects, the Windows one included', () => {
  const hook = init.indexOf('StealthSelectGeolocationProvider(mProvider)');
  assert.ok(hook > 0);
  assert.equal(init.split('StealthSelectGeolocationProvider(').length, 2);
  assert.ok(init.indexOf('obs->AddObserver(this, "xpcom-shutdown", false);') < hook);
  for (const marker of ['#ifdef MOZ_WIDGET_ANDROID', 'geo.provider.use_mls',
    'MOZ_WIDGET_COCOA', 'new PortalLocationProvider()', 'new GeoclueLocationProvider()',
    '#ifdef XP_WIN', 'ms-windows-location', 'new WindowsLocationProvider()'])
    assert.ok(init.indexOf(marker) > hook, marker + ' must come after the hook');
});

test('the only `new WindowsLocationProvider` of the tree is in GeolocationService::Init, below our guard', () => {
  const out = lines(gitGrep(['-nE', 'new +WindowsLocationProvider', '--', '.', ':!juggler/tests/*']));
  assert.equal(out.length, 1, out.join('\n'));
  assert.ok(out[0].startsWith(SERVICE + ':'), out[0]);
  const at = service.indexOf('new WindowsLocationProvider()');
  assert.ok(at > service.indexOf('nsresult GeolocationService::Init()'));
  assert.ok(at < service.indexOf('GeolocationService::~GeolocationService()'));
  assert.ok(at > service.indexOf('StealthSelectGeolocationProvider(mProvider)'));
  // The guard is a return: nothing between it and the block can run.
  assert.match(init, /if \(StealthSelectGeolocationProvider\(mProvider\)\) return NS_OK;/);
  // No other file names the provider's class (its own files and the include of Init aside).
  const names = gitGrep(['-lE', 'WindowsLocationProvider', '--', '.', ':!juggler/tests/*']);
  for (const f of lines(names))
    assert.ok(f === SERVICE || f.startsWith('dom/system/windows/location/'), f);
});

test('the only caller of GetWindowsUtilsPromise (the only start of the WINDOWS_UTILS process) is WindowsLocationProvider', () => {
  const out = gitGrep(['-nE', 'GetWindowsUtilsPromise|ReleaseWindowsUtils', '--', '*.cpp', '*.h', '*.mm', '*.js', '*.mjs', ':!juggler/tests/*']);
  for (const line of lines(out))
    assert.match(line, /^(ipc\/glue\/UtilityProcessManager\.(cpp|h)|dom\/system\/windows\/location\/WindowsLocationProvider\.cpp):/, line);
  const callers = lines(out).filter(l => l.startsWith('dom/system/windows/location/WindowsLocationProvider.cpp:'));
  assert.equal(callers.length, 2, 'one GetWindowsUtilsPromise and one ReleaseWindowsUtils');
  // Inside the manager, the only uses are the definitions themselves.
  const cpp = read('ipc/glue/UtilityProcessManager.cpp');
  const calls = cpp.split('\n').filter(l => /GetWindowsUtilsPromise|ReleaseWindowsUtils/.test(l) &&
    !/^UtilityProcessManager::GetWindowsUtilsPromise\(\) \{|^void UtilityProcessManager::ReleaseWindowsUtils|"UtilityProcessManager::GetWindowsUtilsPromise"|LaunchError\("GetWindowsUtilsPromise|PWindowsUtils|WindowsUtilsPromise>/.test(l));
  assert.deepEqual(calls, []);
  // The process kind starts in one place, and the parent actor that asks for it is made in one place.
  assert.deepEqual([...new Set(lines(gitGrep(['-nE', '(Sandboxing|Sbox)Kind::WINDOWS_UTILS', '--', '*.cpp', '*.h', ':!juggler/tests/*']))
    .map(l => l.split(':')[0]))].sort(), [
    'ipc/glue/UtilityProcessManager.cpp', 'security/sandbox/win/src/sandboxbroker/sandboxBroker.cpp',
    'toolkit/xre/nsAppRunner.cpp'].sort());
  assert.deepEqual(lines(gitGrep(['-lE', 'new +dom::WindowsUtilsParent|SendStartWindowsUtilsService', '--', '*.cpp', '*.h', ':!juggler/tests/*'])).sort(), [
    'dom/system/windows/WindowsUtilsParent.h', 'ipc/glue/UtilityProcessManager.cpp'].sort());
});

test("geo.provider.ms-windows-location is read only by Init, below the guard; its default is Mozilla's", () => {
  const out = lines(gitGrep(['-n', 'ms-windows-location', '--', '.', ':!juggler/tests/*']));
  assert.deepEqual([...new Set(out.map(l => l.split(':')[0]))].sort(), ['modules/libpref/init/all.js', SERVICE]);
  assert.ok(init.indexOf('ms-windows-location') > init.indexOf('StealthSelectGeolocationProvider(mProvider)'));
});

test('the actors of the provider are named only by the provider, the utility child Mozilla wrote for it, and a metric description', () => {
  const out = gitGrep(['-lE', 'PWindowsLocation|WindowsLocation(Child|Parent)|WindowsRuntimeLocation|WindowsLegacyLocation',
    '--', '.', ':!juggler/tests/*', ':!dom/system/windows/*']);
  for (const f of lines(out)) assert.equal(f, 'dom/geolocation/metrics.yaml', f);
});

test('the own file picks the network provider by contract and reads neither a pref nor the host', () => {
  const cpp = read(OWN_CPP);
  const header = read(OWN_H);
  assert.match(cpp, /bool StealthSelectGeolocationProvider\(\s*nsCOMPtr<nsIGeolocationProvider>& aProvider\)/);
  assert.match(cpp, /do_GetService\(StealthGeolocationProviderContract\(\)\)/);
  assert.match(cpp, /return true;/);
  assert.match(header, /const char\* StealthGeolocationProviderContract\(\);/);
  assert.match(cpp, /return "@mozilla\.org\/geolocation\/provider;1";/);
  for (const bad of [/Preferences::/, /StaticPrefs::/, /WindowsLocationProvider/, /ms-windows-location/,
    /XP_WIN/, /MOZ_WIDGET/, /WinRT|Geolocator|wlanapi/i])
    assert.doesNotMatch(cpp, bad);
});

test('the own file is registered in the build by lines after the closing bracket, marked STEALTH-HOOK', () => {
  const build = read('toolkit/components/geolocation/moz.build');
  assert.ok(build.includes(
    `EXPORTS.mozilla += [\n    "GeolocationService.h",\n]\n` +
    `EXPORTS.mozilla += ["StealthGeolocation.h"]  # STEALTH-HOOK(${FOLDER})\n`));
  assert.ok(build.includes(
    `UNIFIED_SOURCES += ["StealthGeolocation.cpp"]  # STEALTH-HOOK(${FOLDER})\n`));
  assert.ok(build.includes(`TEST_DIRS += ["test/gtest"]  # STEALTH-HOOK(${FOLDER})\n`));
  const gtestBuild = read('toolkit/components/geolocation/test/gtest/moz.build');
  assert.ok(gtestBuild.includes('UNIFIED_SOURCES += ["TestStealthGeolocation.cpp"]'));
  assert.ok(gtestBuild.includes('FINAL_LIBRARY = "xul-gtest"'));
});

test("the gtest row is in the suite the candidate's filter runs (StealthDeclaredNetwork)", () => {
  const gtest = read('toolkit/components/geolocation/test/gtest/TestStealthGeolocation.cpp');
  assert.match(gtest, /TEST\(StealthDeclaredNetwork, GeolocationProviderIsTheNetworkProviderOnEveryOS\)/);
  assert.match(gtest, /StealthGeolocationProviderContract\(\)/);
  assert.match(gtest, /NS_GEOLOCATION_PROVIDER_CONTRACTID/);
});
