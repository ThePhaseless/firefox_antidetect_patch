# fingerprint/js-surface/branding

Category: build, other, spoof
Prefs: zoom.stealth.branding.archive (read in netwerk/protocol/res/StealthBranding.cpp; no pref in a Mozilla file)
Test: StealthBranding.* gtests (netwerk/protocol/res/gtest/TestStealthBranding.cpp: both roads give the same jar, engine off is the control;
security/sandbox/linux/gtest/TestStealthBrandingPolicy.cpp: the Linux content policy); the Windows content sandbox rule by the wrapper e2e
tests/test_branding_is_declared_windows_sandbox_e2e.py; the declaration side by the release gate platform/ci/src/scripts/stock_parity.py
(serves_declared_branding) and the core's tests/test_branding.py, test_branding_source.py, test_brand_prefs_are_the_cores.py

## What it does

The branding a page can read (the about dialog's stylesheet rules, the wordmarks' boxes, the images' sizes) tells a build from the retail
one, so it is declared by invisible_core, files and all: `zoom.stealth.branding.archive`, a file: URI of a zip archive whose root entries
are the files. The engine keeps no copy of any of them and serves the declared ones as jar: - the channel class the retail serves its
branding with out of omni.ja, so a page sees the same channel behaviour (a file: channel keeps a loader's content-type hint, a jar: one
does not). Engine off (no seed) is stock Firefox and serves the build's own brand. Engine on and nothing, or something malformed,
declared: the launch is refused by the declaration gate, and a load that still gets here fails (NS_ERROR_FILE_NOT_FOUND) instead of
serving the build's own brand.

A page reaches the branding directory two ways: chrome://branding/content/ (the package is contentaccessible) and
resource://usercontext-content/branding/ (that host maps the whole of browser/content/). Both end in a URI under the branding package's
content directory, so the redirect is one function (`StealthBrandingRedirect`) applied at the two places that resolve those URIs; a page
comparing the two ways gets the same files by construction.

- The chrome registries, in the parent and in every content process, record the branding package's content directory when they register
  a package (`StealthBrandingRegisterPackage`; the last registration wins, a registry reset re-registers every package, a package with
  no content directory in this process is ignored). The content process resolves branding URIs itself, so it needs the directory too.
- `nsChromeRegistry::ConvertChromeURL`'s last step goes through `StealthBrandingChromeURL`: it takes the URI Mozilla resolved, runs its
  spec through the redirect and, if the spec changed, releases it and builds the URI of the declared jar; unchanged (engine off, or not
  a branding URI), the URI Mozilla resolved is returned as it is.
- `SubstitutingProtocolHandler::ResolveURI` is ours (StealthBranding.cpp): it calls Mozilla's body, now `ResolveURI_Mozilla`, and
  applies the redirect to every successful result, the special cases (`ResolveSpecialCases`) included; a failure is returned as it is.
  Every caller (the other handlers, `ResolveJARURI`, `NewChannel`, `SetSubstitutionWithFlags`) calls it by its name and so goes through
  it. The only difference to the previous hooks is the order against Mozilla's debug log line (MOZ_LOG `nsResProtocol:5`), which now
  prints the spec before the redirect; a page cannot read it.
- The content sandboxes get READ access to exactly the declared archive, the file `StealthBrandingDeclaredArchive` accepted (the same
  function the declaration gate uses, so a launch the gate lets through is one whose content processes can read the files): on Linux
  one read-only rule added to the policy in `SandboxBrokerPolicyFactory::InitContentPolicy` (`StealthBrandingAddReadRule`,
  StealthLinuxSandboxBranding.h), on Windows one `AllowFileAccess` rule added to the content configuration, between the profile's
  chrome and extensions directory rules (`StealthBrandingAddReadRule`, StealthSandboxBranding.h). A rule that cannot be added is
  reported with NS_ERROR on Windows and is not fatal; nothing is added when the declaration is not usable.

## Hooks in Mozilla files

- `chrome/nsChromeRegistry.cpp`: an include in a block of ours, and a wrap of the expression `NS_NewURI(aResult, path, nullptr, baseURI)`
  in the last statement of `ConvertChromeURL` (`StealthBrandingChromeURL`).
- `chrome/nsChromeRegistryChrome.cpp`: an include, and an anchor in `ManifestContent` after `entry->flags = flags;`
  (`StealthBrandingRegisterPackage(packageName, entry->baseURI)`: it needs the base URI the two statements above produce).
- `chrome/nsChromeRegistryContent.cpp`: an include, and an anchor in `RegisterPackage` after the three NS_NewURI blocks
  (`StealthBrandingRegisterPackage(aPackage.package, content)`: it needs the local `content`; the null check is in our function).
- `netwerk/protocol/res/SubstitutingProtocolHandler.cpp` and `.h`: the function wrap, the signature of Mozilla's `ResolveURI` renamed
  `ResolveURI_Mozilla` and its declaration after `NS_DECL_NON_VIRTUAL_NSISUBSTITUTINGPROTOCOLHANDLER`.
- `netwerk/protocol/res/moz.build`: our header, our source and the gtest directory, after the closing brackets.
- `security/sandbox/linux/broker/SandboxBrokerPolicyFactory.cpp`: an include and an anchor after the `read_path_whitelist` rules in
  `InitContentPolicy` (`StealthBrandingAddReadRule(policy)`: it adds to the local `policy`, in that place, so the order of the rules
  does not change). `security/sandbox/linux/gtest/moz.build`: our gtest, after the closing bracket.
- `security/sandbox/win/src/sandboxbroker/sandboxBroker.cpp`: an include and an anchor between the chrome and extensions directory rules in
  `SetSecurityLevelForContentProcess` (`StealthBrandingAddReadRule(config)`: it adds to the local `config` inside the `else` branch).

Two Mozilla lines are rewritten (the expression wrap and the signature); no other Mozilla line is removed or changed.

## Our own files

- `netwerk/protocol/res/StealthBranding.{h,cpp}` (the declaration, the redirect, the two wrappers, `ResolveURI`)
- `security/sandbox/linux/broker/StealthLinuxSandboxBranding.h`, `security/sandbox/win/src/sandboxbroker/StealthSandboxBranding.h`
- `netwerk/protocol/res/gtest/{TestStealthBranding.cpp,moz.build}`, `security/sandbox/linux/gtest/TestStealthBrandingPolicy.cpp`
