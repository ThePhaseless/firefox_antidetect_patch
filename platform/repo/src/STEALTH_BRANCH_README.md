# Invisible Firefox - branch `stealth/150`

This branch (`stealth/150`), on the fork of `mozilla-firefox/firefox`, is the **single source of truth** for the stealth patches applied to Firefox 150.0.1.

> History: this repository was called `firefox` until 2026-05-19, and there was a companion repository with the numbered .patch files. Both were consolidated here (rename + delete). See the commit `ce71f1f...` in the wrapper repository for the rename trail.

## Status (2026-05-19)

- **Base**: `stealth-base/v150.0.1` -> tag `FIREFOX_150_0_1_RELEASE` of `mozilla-firefox/firefox` (`ec9aaac47d4c...`)
- **HEAD**: branch tip (`6ca01bfe0ca9...`)
- **Commits ahead**: 25 commits above `stealth-base/v150.0.1`
- **Build status**: clean COMPILE, RUNTIME works - `firefox.exe` + Playwright + Juggler pipe + new_page + page.mouse.* all pass on the clean build. Remaining gap: locale="en-US" via `Browser.setLocaleOverride` crashes the content process after ~30s (workaround: `locale=""` on `InvisiblePlaywright`).

### Summary of recent fixes (C1-C7)

| Gap | Commit | What |
|---|---|---|
| C1+C2 | `8feb68c7dc22` | re-land setDownloadInterceptor (IDL + cpp + .h member) |
| C4 | `2495f9447cd9` | re-land 5 nsIDocShell stealth attributes (fileInputInterceptionEnabled, overrideHasFocus, bypassCSPEnabled, forceActiveState, disallowBFCache) |
| C5 | `951efca4f9f6` | port FF146 launcher+wmain juggler-pipe handle inheritance: without this the Playwright->browser pipe disconnects immediately |
| C6 | `bec3da1e65e2` | port juggler-navigation-started observer notifications in nsDocShell.cpp + CanonicalBrowsingContext.cpp: without this Page.ready is never emitted and ctx.new_page() hangs |
| C7 (partial) | `6ca01bfe0ca9` | storage-only stub for nsIDocShell.languageOverride; the full port requires a BrowsingContext FIELD + ICU/JS locale reset (multi-file, to be done later) |

## Branch history

```
2f0dbec  fix(juggler): port 7 dist hand-patches into source (FF150 Fission, screencast stub, try/catch)
619db115 fix(juggler): disable screencast + try/catch on screencastService (FF150 libwebrtc gap)
eb135ac7 build: add missing libwebrtc/api/location.h + nICEr ice_component.c (FF150 patch series gap)
86f82412 fix(juggler): re-land jugglerSendMouseEvent C++ for FF150 (issue #9)
[+15 commits, application of 0001-build-infra.patch ... 0015-storage-quota.patch (originally from the companion patch repository, now consolidated as commits here)]
ec9aaac4 [stealth-base/v150.0.1] FF150_0_1_RELEASE vanilla mozilla-firefox
```

## Workflow for making new changes

### 1. Clone this branch
```bash
git clone -b stealth/150 <url-of-this-fork> firefox-source
cd firefox-source
```

### 2. Development: edit, commit, push
```bash
# Edit the files that are needed
git add <files>
git commit -m "fix(area): description"
git push origin stealth/150
git tag -f stealth-head/v150.0.1 HEAD
git push origin stealth-head/v150.0.1 --force
```

### 3. Build (~30-60 min cold, 5-30min incremental)
```bash
./mach.cmd bootstrap --no-system-changes --application-choice=browser  # first time only
./mach.cmd build
```

### 4. Test
- E2E mouse suite: `release/stealthfox/tests/test_mouse.py` (12 cases)
- Stealth: public fingerprinting test pages, a commercial fingerprinting service, a public bot-detection test page, a captcha service

### 5. When the branch produces a clean build + green tests, regenerate the patch series

```bash
git format-patch stealth-base/v150.0.1..stealth/150 -o ../patch-series/
# Manually: rename and bucket-group into the 15 numbered .patch files for compat with the existing README
cd ../patch-series
git add 000*.patch
git commit -m "regen from stealth/150 branch"
git push origin main
```

## Remaining gaps for a clean build that WORKS at runtime

Gaps C1-C7 have been ported. The only gap LEFT is the completion of C7.

### C7. (Partial -> to complete) `languageOverride` BrowsingContext FIELD
The stub committed in `6ca01bfe0ca9` keeps `docShell.languageOverride = locale` as a no-op (storage only). The full fix requires:
- BrowsingContext FIELD `LanguageOverride` (with `DidSet`/`CanSet` callbacks) for cross-process propagation
- `SetIcuLocale(aLanguageOverride)` callback with `icu::Locale::setDefault`, `JS_ResetDefaultLocale`, `ResetDefaultLocaleInAllWorkers`
- Multi-file: `BrowsingContext.{h,cpp}`, `CanonicalBrowsingContext.cpp` (txn.SetLanguageOverride), `nsDocShell.cpp` (call SetIcuLocale)

Symptom of the C7 gap: `Browser.setLocaleOverride` with `locale="en-US"` (default of `InvisiblePlaywright`) crashes the content process after ~30 seconds (GPU init timeout). Workaround: pass `locale=""` explicitly.

### C3. (Optional) Screencast: `HeadlessWindowCapturer` + `VideoCaptureModuleEx`
Requires patches to `third_party/libwebrtc` for the types `VideoCaptureModuleEx` + `RawFrameCallback`. Complicated because mozilla may have removed them from upstream libwebrtc. For now **DISABLED** (no-op stub in `juggler/TargetRegistry.js`).

## What stealth/150 currently does

- Clean compile (no errors, 1 warning that already exists upstream)
- `jugglerSendMouseEvent` C++ properly landed (issue #9 fix)
- `juggler/` correctly hooked into the build (toolkit.mozbuild DIRS)
- FF150 Fission cross-process navigation handlers (FrameTree.js, JugglerFrameParent.sys.mjs)
- `setDownloadInterceptor` IDL + cpp + .h member (C1+C2)
- `nsIDocShell` 5 stealth attributes (C4)
- Launcher -> child juggler-pipe handle inheritance (C5)
- Juggler navigation observer notifications (C6)
- Stealth works: webdriver=False, UA override, languages, page.mouse.* OK
- WARNING: `Browser.setLocaleOverride` with a non-empty locale crashes the content process after 30s (C7 partial, workaround `locale=""`)

## firefox-2 SHIPPED remains canonical

For users, `firefox-2` (a release of the wrapper repository) is the stable binary:
- Built May 3 2026 on the local working tree that had all the changes
- Its `xul.dll` (sha256 `97b38e1bc3a6cdfd...`) contains 3 extra C++ symbols compared to a build from a clean fork
- Mouse suite test: 8/12 PASS (4 failures are Playwright/timing flakiness, not stealth/build)

## Reference: the 7 hand-patched Juggler files (captured in commit `2f0dbec`)

| File | What | Lines |
|---|---|---|
| `juggler/components/Juggler.js` | debug dump on pipe disconnect | +1 |
| `juggler/TargetRegistry.js` | screencast stub + setDownloadInterceptor handling | +73/-10 |
| `juggler/SimpleChannel.js` | class -> var for hot-reload compat | +3/-3 |
| `juggler/JugglerFrameParent.sys.mjs` | FF150 Fission 2-actor routing + pending actor registry | +26/-1 |
| `juggler/content/JugglerFrameChild.jsm` | try/catch removeListeners | +4 |
| `juggler/content/JugglerFrameChild.sys.mjs` | try/catch removeListeners | +4 |
| `juggler/content/FrameTree.js` | FF150 Fission cross-process abort + try/catch | +17 |

## Reference: the 4 modified source files (besides the 15 official patches)

| File | What | Lines |
|---|---|---|
| `toolkit/toolkit.mozbuild` | adds `"/juggler",` to DIRS | +1 |
| `xpcom/reflect/xptinfo/xptinfo.h` | PARAM_BUFFER_COUNT 14 -> 15 | +3 |
| `third_party/libwebrtc/api/location.h` | NEW file 352 bytes | NEW |
| `dom/media/webrtc/transport/third_party/nICEr/src/ice/ice_component.c` | NEW file 74k bytes | NEW |

## Updating to a new Firefox version

The repository (`main` of oss-invisible/firefox_antidetect_patch) holds only the patch
series; the port is done with its tools, not with a rebase of this tree:

```bash
python tools/engine.py drift --to FIREFOX_<N>_0_RELEASE   # our Mozilla files that changed
python tools/engine.py port  --to FIREFOX_<N>_0_RELEASE   # every folder three-way, all the conflicts
```

Only from the tag of the stable release, never from a beta. The full flow is in
the series' `AGENTS.md`.

## See also

- Python wrapper + binary releases: the wrapper repository
