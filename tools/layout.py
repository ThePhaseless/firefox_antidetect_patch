"""Where every change of ours lives in the engine layout.

The layout is one folder per feature, grouped by what the feature does:

    platform/     the build, the branding, the repo's own tooling
    stillborn/    Firefox services we kill at birth (updater, telemetry, ...)
    network/      proxies, SOCKS, DoH
    automation/   what the Juggler protocol needs from Gecko
    fingerprint/  what a page can observe, one folder per surface
    port/         fixes tied to one Firefox version, each with its reason to expire

GROUP_ORDER is also the order the series is applied in.

FEATURES maps the feature names of the inventory (tools/inventory.json, one
record per Mozilla file we modify) to their folder. The files we add to Firefox's tree have no table:
the folder that holds `<folder>/src/<path>` owns it (own_file_folder); a file the series has not seen yet is
placed once, by `export --own <path>=<folder>`.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from failure import fail  # noqa: E402

RULE = "series-01-export-is-the-only-writer"      # layout.py is one of the files edited by hand; the export stops until it names the owner

GROUP_ORDER = ["platform", "stillborn", "network", "automation", "fingerprint", "port"]

FEATURES = {
    # platform
    "release-output-ignore": "platform/repo",
    "agent-instructions-fork": "platform/repo",
    "readme-fork-disclosure": "platform/repo",
    "anonymous-launch-counter": "platform/launch-counter",
    "hidden-desktop-window-capture": "platform/hidden-desktop",
    "script-cache-adopt-written": "platform/script-cache",
    "startup-cache-foreground-writes": "platform/startup-cache",
    "wr-shared-fonts-cleared-with-namespace": "platform/webrender-memory",
    "untrusted-modules-own-binaries": "platform/untrusted-modules",
    "gfx-feature-status-declared": "platform/declaration-gate",
    "stealth-prefs-content-sync": "platform/prefs",
    "firefox-js-stealth-defaults": "platform/prefs",
    "stealth-pref-declarations": "platform/prefs",
    "stealth-pref-defaults": "platform/prefs",
    "vsdownload-download-watchdog": "platform/build-tools",
    "win-long-build-paths": "platform/build-tools",
    # platform: commits of Mozilla's repository carried before the tag has them
    "fontconfig-face-index": "platform/backports/fontconfig-face-index",
    # platform: commits of mozilla/glean carried before the glean-core Mozilla vendors has them
    "glean-init-shutdown-race": "platform/backports/glean-init-shutdown-race",
    # stillborn
    "updater-refuses": "stillborn/updater",
    "pingsender-session-route": "stillborn/telemetry",
    "api-keys-declared": "stillborn/api-keys",
    "security-state-declared": "stillborn/security-state",
    # network
    "ipv6-literal-connect": "network/ipv6-literal",
    "proxy-udp-egress": "network/proxy-udp",
    "system-proxy-default-off": "network/proxy",
    "socks-credentials": "network/socks",
    "doh-trr-context": "network/doh",
    "geolocation-no-host-provider": "fingerprint/geolocation/no-host-provider",
    # automation
    "juggler-build": "automation/juggler",
    "juggler-prefs": "automation/juggler",
    "juggler-frame-crash-context": "automation/juggler",
    "bypass-csp": "automation/bypass-csp",
    "closed-shadowroot-automation-access": "automation/shadow-root",
    "shadow-root-sandbox-access": "automation/shadow-root",
    "file-chooser-intercept": "automation/file-chooser",
    "hybrid-xrays": "automation/hybrid-xrays",
    "juggler-docshell-attrs": "automation/docshell-attrs",
    "juggler-download-interceptor": "automation/downloads",
    "juggler-drag-gesture": "automation/input",
    "juggler-element-atoms": "automation/element-atoms",
    "juggler-enterprise-policies": "automation/enterprise-policies",
    "juggler-event-id": "automation/input",
    "juggler-mouse-event-id": "automation/input",
    "juggler-input-dispatch": "automation/input",
    "juggler-param-buffer": "automation/input",
    "juggler-forced-offline": "automation/forced-offline",
    "juggler-ignore-https-errors": "automation/ignore-https-errors",
    "juggler-interception": "automation/network-interception",
    "juggler-service-worker-intercept": "automation/network-interception",
    "juggler-link-click-events": "automation/navigation",
    "juggler-navigation-events": "automation/navigation",
    "juggler-load-identifier": "automation/navigation",
    "juggler-pipe-handles": "automation/pipe",
    "juggler-pipe-stdio": "automation/pipe",
    "juggler-popup-explicit-size": "automation/window-size",
    # fingerprint: fonts
    "bundled-fonts-macos": "fingerprint/fonts/bundle",
    "font-bundle-files": "fingerprint/fonts/bundle",
    "font-bundle-borrow": "fingerprint/fonts/bundle",
    "font-bundle-borrowed-bytes": "fingerprint/fonts/bundle",
    "font-bundle-file-path": "fingerprint/fonts/bundle",
    "font-ttc-face-index": "fingerprint/fonts/bundle",
    "font-cmap-publish": "fingerprint/fonts/bundle",
    "hb-face-lifetime": "fingerprint/fonts/bundle",
    "font-fallback-bundle": "fingerprint/fonts/bundle",
    "font-list-bundle-only": "fingerprint/fonts/font-list",
    "font-design-metrics": "fingerprint/fonts/metrics",
    "font-metrics-declared": "fingerprint/fonts/metrics",
    "glyph-coverage-quantise": "fingerprint/fonts/metrics",
    "cleartype-declared": "fingerprint/fonts/metrics",
    "font-loading-api-inert": "fingerprint/fonts/font-loading",
    # fingerprint: canvas, webgl
    "canvas-noise-projection": "fingerprint/canvas/noise-projection",
    "canvas-as-drawn-readers": "fingerprint/canvas/as-drawn",
    "canvas-snapshot-readback": "fingerprint/canvas/as-drawn",
    "canvas-2d-text-metrics": "fingerprint/canvas/text-metrics",
    "webgl-parameters": "fingerprint/webgl/parameters",
    "webgl-shader-output-language": "fingerprint/webgl/shader-language",
    "webgl-multisample": "fingerprint/webgl/multisample",
    "webgl-own-gl": "fingerprint/webgl/own-gl",
    # fingerprint: audio, media
    "audio-context-values": "fingerprint/audio/context-values",
    "audio-fingerprint-noise": "fingerprint/audio/noise",
    "audio-sample-rate": "fingerprint/audio/sample-rate",
    "media-decode-declaration": "fingerprint/media/decode-declaration",
    "media-codecs-declared": "fingerprint/media/decode-declaration",
    "media-enumeration": "fingerprint/media/enumeration",
    "speech-voices-declared": "fingerprint/media/speech-voices",
    # fingerprint: the text engine of every OS (phase 4)
    "idwr-text-engine": "fingerprint/fonts/idwr",
    # fingerprint: webgpu
    "webgpu-adapter-declaration": "fingerprint/webgpu/adapter-declaration",
    "webgpu-external-texture-vulkan": "fingerprint/webgpu/external-texture-vulkan",
    # fingerprint: webrtc
    "webrtc-declared-network": "fingerprint/webrtc/declared-network",
    # fingerprint: screen and window
    "screen-metrics": "fingerprint/screen-window/screen",
    "window-geometry": "fingerprint/screen-window/geometry",
    "popup-default-position": "fingerprint/screen-window/popup-position",
    "css-media-features": "fingerprint/screen-window/css-media",
    "occlusion-tracking": "fingerprint/screen-window/occlusion",
    "focus-ignore-os-deactivation": "fingerprint/screen-window/focus",
    # fingerprint: locale and time
    "session-declaration": "fingerprint/locale-time/session-declaration",
    "session-language-declared": "fingerprint/locale-time/language",
    "language-declared": "fingerprint/locale-time/language",
    "accept-language-override-list": "fingerprint/locale-time/accept-language",
    "timezone-declared": "fingerprint/locale-time/timezone",
    "timezone-locale-override": "fingerprint/locale-time/timezone",
    "xslt-date-timezone": "fingerprint/locale-time/timezone",
    "worker-locale-timezone": "fingerprint/locale-time/workers",
    # fingerprint: hardware
    "hardware-profile": "fingerprint/hardware/profile",
    "navigator-hardware-concurrency": "fingerprint/hardware/concurrency",
    "storage-quota-estimate": "fingerprint/hardware/storage-quota",
    # fingerprint: input
    "input-event-birth": "fingerprint/input/event-birth",
    "synthetic-input-latency": "fingerprint/input/latency",
    # fingerprint: what scripts can read about the engine
    "stealth-branding-redirect": "fingerprint/js-surface/branding",
    "debugger-invisible-attach": "fingerprint/js-surface/debugger",
    "devtools-attach-suppressed": "fingerprint/js-surface/debugger",
    "stack-hide-juggler-frames": "fingerprint/js-surface/stack-frames",
    "eval-introduction-name": "fingerprint/js-surface/eval-name",
    "blob-native-endings": "fingerprint/js-surface/line-endings",
    "plaintext-linebreak": "fingerprint/js-surface/line-endings",
}


def folders_on_disk(root: Path) -> list:
    """The folders of a series laid out as `root/<group>/.../MANIFEST.json`, sorted (a MANIFEST.json under a src/ is a file of ours, not a folder)."""
    root = Path(root)
    return sorted(str(p.parent.relative_to(root)).replace("\\", "/")
                  for p in root.glob("*/**/MANIFEST.json")
                  if p.relative_to(root).parts[0] in GROUP_ORDER and "src" not in p.relative_to(root).parts)


def src_owners(root: Path) -> tuple:
    """Who owns each file of ours, read from the series itself: `<folder>/src/<path>` IS the file, so the folder that holds it owns it.
    -> ({path: folder}, [(path, folder, other folder)]): the second list is a path under the src/ of two folders (a failure of `check`)."""
    owner, twice = {}, []
    for folder in folders_on_disk(root):
        src = Path(root) / folder / "src"
        if not src.is_dir():
            continue
        for p in sorted(src.rglob("*")):
            if p.is_file():
                path = p.relative_to(src).as_posix()
                if path in owner:
                    twice.append((path, owner[path], folder))
                else:
                    owner[path] = folder
    return owner, twice


def own_file_folder(path: str, held: dict, declared: dict | None = None) -> str:
    """The folder of a file of ours: the one that holds it under src/ (`held`: src_owners(root)[0]; no table: a table of the same fact is a
    second writer). A file the series has not seen yet, or one that moves, is placed by `declared` (`export --own <path or dir/>=<folder>`,
    the longest key wins and beats the folder that holds it). Once exported, the file is in src/ and nobody needs to say it again."""
    keys = [key for key in (declared or {}) if path == key or (key.endswith("/") and path.startswith(key))]
    if keys:
        return declared[max(keys, key=len)]
    if path in held:
        return held[path]
    raise KeyError(str(fail(
        "python tools/engine.py export", "no folder owns our new file %s: it is under no folder's src/ yet" % path,
        "name its folder once: `--own %s=<folder>` (a folder of SERIES, or a new one under %s); the export then writes the file under that folder's src/ and it is owned from then on"
        % (path, "/".join(GROUP_ORDER)), RULE)))


def feature_folder(feature: str) -> str:
    try:
        return FEATURES[feature]
    except KeyError:
        raise KeyError(str(fail(
            "tools/layout.py FEATURES", "the feature %r has no folder" % feature,
            "add it to FEATURES in tools/layout.py with the folder that owns it, then export again", RULE))) from None


def folder_sort_key(folder: str):
    group = folder.split("/")[0]
    return (GROUP_ORDER.index(group), folder)
