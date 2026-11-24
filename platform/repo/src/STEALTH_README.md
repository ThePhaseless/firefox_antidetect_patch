# firefox_antidetect_patch

[![browser launches](https://raw.githubusercontent.com/oss-invisible/playwright/badges/docs/badges/launches.svg)](https://github.com/oss-invisible/firefox_antidetect_patch/releases/tag/usage-counter)

Firefox, patched at the C++ source level so the browser fingerprint is produced by the
engine instead of being injected into the page. This repository holds the patched
source and publishes the built binaries as releases.

It is the engine behind two projects, and most people want one of those instead of
this repository:

- **[invisible_playwright](https://github.com/oss-invisible/playwright)**, a
  Python wrapper that drives it through the standard Playwright API.
- **[invisible_firefox](https://github.com/feder-cr/invisible_firefox)**, a profile
  manager for running many identities from one desktop app.

Current release: **firefox-18**, built from Firefox 151.0. Branch **`stealth/151`** is
the source of truth; see [STEALTH_BRANCH_README.md](STEALTH_BRANCH_README.md) for the
patch series.

## What is patched, and why it is done here

An injected script has to run inside the page, which means the page can find it. The
override is a function whose source can be printed, its result can be compared against
a value nobody thought to change with it, and a worker or an iframe can ask the same
question in a context the patch never reached. Doing it in the engine removes the seam
instead of hiding it.

The surfaces set from source: navigator and the user agent,
[screen geometry](https://github.com/oss-invisible/playwright/blob/main/docs/screen-size-headless-tells.md),
[WebGL vendor and renderer strings](https://github.com/oss-invisible/playwright/blob/main/docs/webgl-renderer-strings.md)
with [their numeric limits](https://github.com/oss-invisible/playwright/blob/main/docs/webgl-parameters-are-identical.md),
canvas pixel output, [the font set](https://github.com/oss-invisible/playwright/blob/main/docs/bundled-fonts-cross-platform.md),
[the audio pipeline](https://github.com/oss-invisible/playwright/blob/main/docs/audiocontext-fingerprinting.md),
[WebRTC ICE candidates](https://github.com/oss-invisible/playwright/blob/main/docs/webrtc-ice-candidate-spoofing.md),
timezone, locale, and the proxy path.

Every value arrives through a preference, so nothing is hardcoded in C++ and one seed
reproduces one machine. What each of those surfaces reveals, and what it costs to get
right, is written up one at a time in the pages linked above.

## Pointer input and page zoom

Juggler accepts pointer positions in page CSS pixels. Mouse input, native
cursor motion and wheel hit positions account for the page's current browser
zoom, including site-specific zoom restored from a persistent profile.
Device scaling is handled separately by Gecko; callers should not multiply
pointer coordinates by `window.devicePixelRatio`. Landing verification remains
enabled.

## Anonymous launch counter

This build issues a single HTTPS GET to a public asset on
[oss-invisible/firefox_antidetect_patch](https://github.com/oss-invisible/firefox_antidetect_patch/releases/tag/usage-counter)
every time the browser process starts. That asset's `download_count` is the global
launch counter in the badge above, which also carries the 1,162,836 launches counted
before 2026-07-22 (the asset was hosted elsewhere until then, and its count cannot be
carried over, so the badge adds the two).

What is sent:

- One `GET https://github.com/oss-invisible/firefox_antidetect_patch/releases/download/usage-counter/launch.txt`
- A standard Firefox User-Agent. No identifiers, no payload, no cookies.

When it fires:

- At `final-ui-startup`, before any tab exists and before web content can observe the
  request from a page context.
- Fire and forget. Errors are swallowed and the browser never blocks on the network.

It is not optional: the request is made at every start, to this address, and nothing
in the package or in a setting skips it or moves it. The address is a constant in
[`browser/components/StealthLaunchCounter.sys.mjs`](browser/components/StealthLaunchCounter.sys.mjs).

Why it exists: the build is given away, and archive download counts both undercount
and overcount, because caches and mirrors hide real installs while CI re-pulls inflate
them. A per-launch ping is the closest honest signal of how many installs are real.

## Bugs and questions

File them in this repository's issue tracker. Please do not file them at Mozilla: this
is an unaffiliated fork, and the patches here are not theirs.

---

# Firefox (upstream)

This project is a fork of Firefox. It is not affiliated with or endorsed by Mozilla.
The upstream project's own README follows, because everything in it is still true of
the code this fork is built on.
