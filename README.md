# firefox_antidetect_patch, linux-arm64 fork

This fork of [oss-invisible/firefox_antidetect_patch](https://github.com/oss-invisible/firefox_antidetect_patch) builds upstream's stealth Firefox natively for linux-arm64 on GitHub's `ubuntu-24.04-arm` runner, with no x86 emulation. It is pinned to upstream tag `firefox-58` (Firefox 159.0, BuildID 20261108115355), the tag Byparr's `uv.lock` pins through `invisible-core 58.56.0`.

## What this fork is, and what it is not

It contains only the changes an aarch64 build needs to draw, compute and report what upstream's linux-x86_64 build does. It adds no features and no fixes that upstream lacks, and it leaves the x86 builds as they are. Every hunk in a Mozilla, Skia, ffvpx or Mesa file sits under an aarch64-only guard (`__aarch64__`, `SK_CPU_ARM64`, `DETECT_ARCH_AARCH64`) or in a file only the aarch64 build compiles.

Upstream's patch series stays byte-identical. The fork's changes are an overlay in `arm64/patches/`, applied in order by `arm64/apply.sh` after `tools/engine.py materialize`:

| Patch | What it changes |
| --- | --- |
| `0001-ci-linux-arm64-leg.patch` | Restores the `linux-arm64` CI leg that upstream removed after firefox-55 (`legs.py`, `upstream_toolchain.py`, and the tests that leg breaks). |
| `0002-webgpu-lavapipe-aarch64.patch` | Builds WebGPU's lavapipe driver natively for aarch64, with a fixed CPU profile (`generic`, ARMv8.0 baseline) so no host CPU feature reaches LLVM. This is the aarch64 counterpart of upstream's fixed x86-64 profile. |
| `0003-canvas-aarch64-x86-arithmetic.patch` | Three NEON-only Skia paths (lowp `div255`, the `s32a_opaque` row blit, and the NEON-only legacy filter for rotated image shaders) are turned off on aarch64, so it runs the arithmetic x86 runs. |
| `0004-audio-fft-aarch64-x86-codelets.patch` | ffvpx's FFT codelets for 8, 16 and 32 points and the split-radix combine are ported from x86's FMA3 assembly instruction by instruction, so WebAudio's FFT gives the same bits as on x86. |

The fork's workflows are `.github/workflows/arm64.yml` (build, gate, publish), `arm64-gate.yml` (upstream's `gate.yml` plus the arm64 leg and a leaf-by-leaf diff) and `arm64-fft-harness.yml` (the FFT probe on both architectures). Upstream's own workflows are disabled on the fork, not deleted. The branch `arm64` is the default branch; `main` mirrors upstream.

## Results

Release: [firefox-58-arm64](https://github.com/ThePhaseless/firefox_antidetect_patch/releases/tag/firefox-58-arm64)

Release run: [46020164607](https://github.com/ThePhaseless/firefox_antidetect_patch/actions/runs/46020164607) (commit `df1ffafb`). Every job passed: plan, lavapipe, build-linux-arm64, the gate on linux-arm64, linux-x86_64 and win-x86_64, host-gate, leaf-diff and publish.

- [host-gate](https://github.com/ThePhaseless/firefox_antidetect_patch/actions/runs/46020164607/job/140602595655): upstream's host gate from wrapper `v0.47.1`, run on the arm64 dump beside upstream's own firefox-58 x86 archives. Result: `HOST GATE OK: 0 failures`.
- [leaf-diff](https://github.com/ThePhaseless/firefox_antidetect_patch/actions/runs/46020164607/job/140602595653): every leaf of the linux-arm64 dump against the linux-x86_64 dump, same seeds and DPRs. Result: 6 visits (DPR 1.0 and 1.5, seeds 11, 12 and 13), 98616 checked leaves equal, 0 failures.

Those two jobs' output from the release run ships with the release: [host-gate.txt](https://github.com/ThePhaseless/firefox_antidetect_patch/releases/download/firefox-58-arm64/host-gate.txt), [leaf-diff.txt](https://github.com/ThePhaseless/firefox_antidetect_patch/releases/download/firefox-58-arm64/leaf-diff.txt) and [exceptions.diff](https://github.com/ThePhaseless/firefox_antidetect_patch/releases/download/firefox-58-arm64/exceptions.diff).

The proof uses the versions Byparr pins: wrapper `invisible-playwright v0.47.1` and core `invisible-core v58.56.0`. Newer wrappers read `ab.` keys and add a same-OS check to the compare, so a different wrapper ref needs a new proof.

### The one change to exceptions.json

Upstream's `exceptions.json` has one entry that excuses `control.webgl1` and `control.webgl2` on `linux-x86_64`, because on a Linux host WebGL runs on the host's Mesa llvmpipe. The arm64 leg runs on the same kind of host, so the gate adds `linux-arm64` to that same entry:

```diff
@@ -28,7 +28,7 @@
   "known_defects": [
     {"keys": ["text.*", "blend.*"],
      "why": "phase 4: text from idwr (DWrite 26100) on every OS; today Windows asks the host's DWrite and Linux FreeType"},
-    {"keys": ["control.webgl1", "control.webgl2"], "legs": ["linux-x86_64"],
+    {"keys": ["control.webgl1", "control.webgl2"], "legs": ["linux-x86_64", "linux-arm64"],
      "why": "WebGL draws through the host's driver (llvmpipe here, ANGLE on Windows); a host-independent rasterizer is its own project"}
   ]
 }
```

That is the only change. No entry is added for arm64 alone, and no other key is excused for arm64 alone. The leaf diff still compares the two WebGL keys between the Linux legs and reports them: in the release run both are equal on all 6 visits.

### Keys the gate does not hold to equality

The leaf diff drops `diag.*` keys (diagnostics, not fingerprint output) as the gate does. It follows what the gate excuses on every leg, so these keys are listed with their state but never fail:

- the wrapper's `noise` and `network` entries, both empty in v0.47.1;
- the wrapper's `measurement` entry, `surface.document.hasFocus` (a runtime focus state). In the release run it is equal on all 6 visits.

The gate also excuses `text.*` and `blend.*` on every leg as known defects. The leaf diff does not: it holds every `text.*` and `blend.*` leaf to equality between linux-arm64 and linux-x86_64.

## Not covered

The gate and the leaf diff measure only what their scenes draw and read. The fork makes no claim about the following:

- NaN bit patterns read back through typed arrays.
- WebGPU render bytes, including FMA fusion in lavapipe shaders (LLVM may fuse multiply-adds on aarch64 where x86's fixed profile does not). The gate checks the adapter and device the page sees, not rendered pixels.
- JIT timing.
- Decoded audio bits (`decodeAudioData`): x86 decodes with AVX2 inverse-MDCT assembly that has no aarch64 port.
- The six blend modes that go through x86's approximate `RCPPS` reciprocal: `color-dodge`, `color-burn`, `hue`, `saturation`, `color` and `luminosity`. They are not in the gate's scenes, and x86 itself gives different bytes for them on Intel and AMD.
- Only one arm CPU model was tested: Neoverse-N2, GitHub's `ubuntu-24.04-arm` runner. The x86 gate legs (Linux and Windows) ran on AMD EPYC 7763.
- Android, macOS and Windows on aarch64 are not built.

## Using the engine

The core's packaged seal has no linux-arm64 asset and lists arm64 as retired after firefox-55. A seal file that has the arm64 entry gets past that. The release's `seal.json` has every field and both x86 entries of upstream's firefox-58 seal unchanged (the publish job asserts it), plus this entry:

```json
"firefox-159.0-stealth-linux-arm64.tar.gz": {"arch": "arm64", "build_id": "20261108115355", "entry_rel": "firefox", "omni_sha256": "e745190aead37a0dbb6e9c5aa59be1136871ced7935d706bec7be221a76316c4", "platform": "linux", "sha256": "fc7f83ef1054b200487855cccc3dd390b9a2f8a11677c5e17aaae46a696ebaae", "size": 267696886}
```

The core downloads only from upstream's release URL, so the engine has to be in place before it looks. Point `INVISIBLE_PLAYWRIGHT_ENGINE_DIR` at a directory holding the extracted archive under `firefox-58_159.0_20261108115355/` (the core's content-keyed name, `<tag>_<upstream_version>_<build_id>` from the seal), and `INVISIBLE_SEAL_FILE` at the seal. The archive has `./firefox` and `./application.ini` at its root. The first `invisible_playwright fetch` adopts the tree and writes its stamp, `.invisible-seal.json`, into it (it needs write access to that directory once), and no download happens. After that, a user without write access gets stamp hits. Each process prints `invisible-core: substituted seal in effect: …` once on stderr.

### Byparr

A design for Byparr's Dockerfile (amd64 keeps the packaged seal and upstream's download):

```dockerfile
FROM base AS engine-amd64

FROM base AS engine-arm64
ARG ARM64_SEAL_SHA256=54212351d31d5faaa2501b22c1aaabf8337f57d727bb499dd39a35808a8cc37b
ARG ARM64_ARCHIVE_SHA256=fc7f83ef1054b200487855cccc3dd390b9a2f8a11677c5e17aaae46a696ebaae
ENV INVISIBLE_SEAL_FILE=/opt/invisible/seal.json \
    INVISIBLE_PLAYWRIGHT_ENGINE_DIR=/opt/invisible/engine
RUN mkdir -p /opt/invisible/engine/firefox-58_159.0_20261108115355 \
 && curl -fsSL -o /opt/invisible/seal.json https://github.com/ThePhaseless/firefox_antidetect_patch/releases/download/firefox-58-arm64/seal.json \
 && echo "$ARM64_SEAL_SHA256  /opt/invisible/seal.json" | sha256sum -c - \
 && curl -fsSL -o /tmp/ff.tgz https://github.com/ThePhaseless/firefox_antidetect_patch/releases/download/firefox-58-arm64/firefox-159.0-stealth-linux-arm64.tar.gz \
 && echo "$ARM64_ARCHIVE_SHA256  /tmp/ff.tgz" | sha256sum -c - \
 && tar xzf /tmp/ff.tgz -C /opt/invisible/engine/firefox-58_159.0_20261108115355 \
 && rm /tmp/ff.tgz

# TARGETARCH is predefined in the global scope, so FROM can use it
FROM engine-${TARGETARCH} AS app
# ... the existing app stage; its root-time `uv run python -m invisible_playwright fetch`
# adopts and stamps /opt/invisible/engine at build time
```

- `ARM64_ARCHIVE_SHA256` is the `sha256` of the arm64 entry in the seal. Both values come from the release's `checksums.txt`; a new fork release means updating both.
- The base stage has curl and coreutils but no python3, so both files are checked with `sha256sum -c`.
- Extract straight into `firefox-58_159.0_20261108115355`. A legacy `firefox-58` tree written in an earlier image layer cannot be renamed to that name on overlayfs (EXDEV), so the core stamps the wrong directory, adopts again at every start, and fails with `PermissionError` as uid 1000.
- The engine sits in `/opt/invisible/engine`, outside `/cache`, so a volume or tmpfs over `/cache` cannot hide it. `/cache` keeps only machine state (geoip, fonts) and its existing `chmod -R a+rwX`.
- Both variables stay set at runtime. Without `INVISIBLE_SEAL_FILE` the core refuses arm64 as a retired leg.
- The `devcontainer` stage is left as it is. It runs `invisible_playwright fetch` without the seal file, so on arm64 it fails as it does today.

The adoption was checked on an aarch64 host with a multi-stage build of this recipe on `python:3.13-slim` (`invisible-core 58.56.0`, `invisible-playwright 0.47.1`), downloading from the release URLs. Both files passed `sha256sum -c`. The root-time `fetch` in the app stage printed `adopted the engine already cached at /opt/invisible/engine/firefox-58_159.0_20261108115355 ... no download needed`. In the built image, uid 1000 then got the same path from `fetch` and `ensure_binary()` with `/opt/invisible` root-owned and no write.

## License

The fork's own changes are under 0BSD; see [LICENSE](LICENSE) for the scope. Mozilla files stay under MPL-2.0, and patch hunks to Skia, ffvpx and Mesa files keep those projects' licenses. Upstream's own code is not relicensed.
