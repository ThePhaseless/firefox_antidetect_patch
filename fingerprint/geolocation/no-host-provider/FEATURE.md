# fingerprint/geolocation/no-host-provider

Category: spoof
Prefs: geo.provider.network.url (declared empty once, the hook is on Mozilla's own line in all.js), geo.provider.network.scan (declared false once in StealthPrefs.js)
Test: TestStealthGeolocation.* (toolkit/components/geolocation/test/gtest, in the suite StealthDeclaredNetwork: the network provider contract,
the declared OS switch, the permission monitor skipped only for geolocation); the node tests of juggler/tests (the two first assert the only
entries: the single `new WindowsLocationProvider`, the single caller of GetWindowsUtilsPromise, the single OS read and monitor of the switch):
geolocation_windows_provider_never_selected, geolocation_no_wifi_scan, geolocation_system_switch_declared_on,
geolocation_network_url_is_empty_by_default, geolocation_override_timestamp_is_delivery_time; the wrapper e2e
tests/test_geolocation_reads_nothing_of_the_host_windows_e2e.py (no geolocation.dll, locationframeworkps.dll, wlanapi.dll or
capabilityaccessmanagerclient.dll in any process of the tree, no -sandboxingKind 3 process; stock Firefox in the same window is the control)

## What it does

The position a page reads comes only from the core's declaration (the geolocation override). The engine never asks the host for a
location, a Wi-Fi scan or a privacy switch.

- No host provider. `GeolocationService::Init()` calls `StealthSelectGeolocationProvider(mProvider)` (toolkit/components/geolocation/
  StealthGeolocation.cpp) right after Mozilla's shutdown observer registration and its three early returns, and returns NS_OK
  when it answers true: the provider is the network one (`NetworkGeolocationProvider.sys.mjs`) in every process, so Portal, GeoClue,
  CoreLocation, Android, the Windows provider and the MLS provider a pref could ask for are never created. The hook is an anchor
  guard after `obs->AddObserver`: a guard in the head would copy Mozilla's three checks and the observer registration, a wrap of
  `Init` would let Portal and GeoClue read the host before the provider is replaced. It passes the private field `mProvider`
  (no `friend`). The Windows location provider is in the tree exactly as Mozilla wrote it (`dom/system/windows/location/`,
  `PWindowsUtils.ipdl`, `WindowsUtilsChild`, the `moz.build` files) and is unreachable: the only `new WindowsLocationProvider()` is
  in `Init()` below the guard, and the provider's constructor is the only caller of `UtilityProcessManager::GetWindowsUtilsPromise`,
  the only start of the WINDOWS_UTILS utility process and of the WinRT geolocation modules. A second entry added by Mozilla in a
  later version fails the node test geolocation_windows_provider_never_selected.
- No Wi-Fi scan. `geo.provider.network.scan` is declared false once: its fallback is true and would start the Wi-Fi monitor and
  load wlanapi.dll in the parent.
- No service URL. `geo.provider.network.url` is "" on Mozilla's own line in all.js; on Windows Mozilla declares nothing, so the pref
  has no value. `NetworkGeolocationProvider` finds no URL and answers POSITION_UNAVAILABLE without asking anyone.
- The OS location switch is declared on and never read. `GetGeolocationPermissionBehavior` (GeolocationSystemWin.cpp) and the
  permission monitor of `PermissionObserver.cpp` (`StealthSkipsPermissionMonitor`, true only for the geolocation permission) return
  before `AppCapability("location")` is created (`StealthSystemLocationDeclaredOn`): no capabilityaccessmanagerclient.dll, and a switch off on the host never cancels a request.
- The override's timestamp is the time of each delivery (a getter in juggler/content/main.js, owned by automation/juggler): the page
  reads `position.timestamp - Date.now()` between -2 and 0 ms, never a day ahead.

## Hooks in Mozilla files

- `toolkit/components/geolocation/GeolocationService.cpp`: one include in a block of ours and an anchor guard in `Init()` after
  `obs->AddObserver(this, "xpcom-shutdown", false);` (`if (StealthSelectGeolocationProvider(mProvider)) return NS_OK;`).
  `toolkit/components/geolocation/moz.build`: our source, our header and the gtest directory, after the closing brackets.
- `dom/geolocation/GeolocationSystemWin.cpp`: one include and a one-line guard in the head of `GetGeolocationPermissionBehavior`.
  `dom/permission/PermissionObserver.cpp`: one include and a one-line guard in the head of `EnsureMonitoringInParent`
  (`if (StealthSkipsPermissionMonitor(aName)) return;`; it runs before a debug-only MOZ_ASSERT, and the only caller is in the parent).
- `modules/libpref/init/all.js` (owned by platform/prefs): the empty default of `geo.provider.network.url`.
- No Mozilla line is removed or changed in this folder.

## Our own files

- `toolkit/components/geolocation/StealthGeolocation.{h,cpp}`, `toolkit/components/geolocation/test/gtest/{TestStealthGeolocation.cpp,
  moz.build}`, and the node tests above.
