# network/socks

Category: other
Prefs: network.proxy.socks_username, network.proxy.socks_password
Test: gtest TestStealthSocksCredentials.PrefsChanged and TestStealthSocksCredentials.ReachResolvedProxyInfo
(netwerk/test/gtest/TestStealthSocksCredentials.cpp; the suite is in the gtest filter of the candidate); wrapper e2e
invisible_playwright/tests/test_proxy_socks_auth_e2e.py::test_socks5_auth_creds_sent_and_routed

## What it does

The SOCKS credentials are read from the prefs `network.proxy.socks_username` and `network.proxy.socks_password` and handed to
every proxy that `nsProtocolProxyService::Resolve_Internal` resolves in manual configuration. Mozilla's single
`NewProxyInfo_Internal` call serves every manual-config branch, so the same credentials ride on the HTTP and HTTPS proxy info
too (the gtest checks it). They are kept as plain `nsCString` in two members of the service.

## Hooks in Mozilla files

- `netwerk/base/nsProtocolProxyService.h`: two members, `mSOCKSProxyUsername` and `mSOCKSProxyPassword`, right after
  `mSOCKSProxyVersion` (form member; the state stays in the service, no statics, no mutex).
- `netwerk/base/nsProtocolProxyService.cpp`:
  - the include of `StealthSocksCredentials.h`, in our block after Mozilla's includes;
  - `StealthSocksPrefsChanged(prefBranch, pref, mSOCKSProxyUsername, mSOCKSProxyPassword);` as the first statement of
    `PrefsChanged` (form notice; the two fields are passed, no `friend`). It reads a credential when `pref` is null (startup) or
    names it, empties it when the read fails, strips whitespace. It stands at the head, not where it stood before (after the
    `socks_version` block): the statements between read and write neither of the two members, none of them returns, and the
    final `NotifyProxyConfigChangedInternal` still runs after the credentials are set; at startup, when `SetIntPref` of a legacy
    type re-enters `PrefsChanged` with `network.proxy.type`, no config-changed callback is registered yet and that pass reads no
    credential.
  - `Resolve_Internal`: the first line of Mozilla's `NewProxyInfo_Internal` call takes `mSOCKSProxyUsername` and
    `mSOCKSProxyPassword` as its 5th and 6th arguments instead of two empty strings (wrap of the call with our values; the
    other two lines of the call are Mozilla's). The explanation of the arguments is here, not in the Mozilla file.
- `netwerk/base/moz.build` and `netwerk/test/gtest/moz.build`: registration lines (the `StealthIPv6Literal.cpp` line in
  `netwerk/base/moz.build` is network/ipv6-literal's).

## Our own files

- `netwerk/base/StealthSocksCredentials.{h,cpp}` (`StealthSocksPrefsChanged`; it spells the two pref names out and uses its own
  read helper because both files can share one unified translation unit and `PROXY_PREF` / `proxy_GetStringPref` are
  Mozilla's file-local names),
  `netwerk/test/gtest/TestStealthSocksCredentials.cpp`, `netwerk/test/gtest/stealth.build`.
