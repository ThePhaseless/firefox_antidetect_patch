# firefox_antidetect_patch, linux-arm64 fork

This fork of [oss-invisible/firefox_antidetect_patch](https://github.com/oss-invisible/firefox_antidetect_patch) builds upstream's stealth Firefox natively for linux-arm64 on GitHub's `ubuntu-24.04-arm` runner, with no x86 emulation. It is pinned to upstream tag `firefox-58` (Firefox 159.0, BuildID 20261108115355), the tag Byparr's `uv.lock` pins through `invisible-core 58.56.0`.

## What this fork is, and what it is not

It contains only the changes an aarch64 build needs to draw, compute and report what upstream's linux-x86_64 build does. It adds no features and no fixes that upstream lacks, and it leaves the x86 builds as they are. Every hunk in a Mozilla, Skia, ffvpx or Mesa file sits under an aarch64-only guard (`__aarch64__`, `SK_CPU_ARM64`, `DETECT_ARCH_AARCH64`) or in a file only the aarch64 build compiles. The guards test only the CPU, so an Android, macOS or Windows aarch64 build of this tree would take them too; none is built.

Upstream's patch series stays byte-identical. The fork's changes are an overlay in `arm64/patches/`, applied in order by `arm64/apply.sh` after `tools/engine.py materialize`:

| Patch | What it changes |
| --- | --- |
| `0001-ci-linux-arm64-leg.patch` | Restores the `linux-arm64` CI leg that upstream removed after firefox-55 (`legs.py`, `upstream_toolchain.py`, and the tests that leg breaks). |
| `0002-webgpu-lavapipe-aarch64.patch` | Builds WebGPU's lavapipe driver natively for aarch64, with a fixed CPU profile (`generic`, ARMv8.0 baseline) so no host CPU feature reaches LLVM. On top of that it reproduces two of x86's results. A multiply and an add are never fused, in the shader JIT or in Mesa's own C, because upstream's x86-64 profile has no FMA. Float `min` and `max` flush a subnormal operand to a signed zero, as x86's `minps` and `maxps` do under DAZ. |
| `0003-canvas-aarch64-x86-arithmetic.patch` | Three NEON-only Skia paths (lowp `div255`, the `s32a_opaque` row blit, and the NEON-only legacy filter for rotated image shaders) are turned off on aarch64, so it runs the arithmetic x86 runs. |
| `0004-audio-fft-aarch64-x86-codelets.patch` | ffvpx's FFT codelets for 8, 16 and 32 points and the split-radix combine are ported from x86's FMA3 assembly instruction by instruction, so WebAudio's FFT gives the same bits as on x86. |

The fork's workflows:

- `.github/workflows/arm64.yml`: build, gate, harnesses, publish.
- `arm64-gate.yml`: upstream's `gate.yml` plus the arm64 leg and a leaf-by-leaf diff.
- `arm64-fft-harness.yml`: the FFT probe on both architectures.
- `arm64-lavapipe-harness.yml`: WebGPU compute and render bytes on both architectures.
- `arm64-guard.yml`: keeps upstream's workflows off.

Upstream's workflows stay in the tree unchanged, because `tools/engine.py check` wants them equal to the series' copies. GitHub can disable a workflow only after its first run. `theta-sweeper` is disabled; the others have never run here. `arm64-guard.yml` disables every workflow that is not `arm64*.yml` and cancels its queued and running runs. It runs every 20 minutes on Monday from 03:00 UTC, when `release.yml`'s weekly schedule fires, and once a day. So the first scheduled `release.yml` run can still start, and fail, before the guard disables it. A sync of `main` starts upstream's push workflows there, which the guard cancels at its next run. The branch `arm64` is the default branch; `main` mirrors upstream.

## Results

Release: [firefox-58-arm64](https://github.com/ThePhaseless/firefox_antidetect_patch/releases/tag/firefox-58-arm64)

Release run: [46066665864](https://github.com/ThePhaseless/firefox_antidetect_patch/actions/runs/46066665864) (commit `73bde4f9`). Every job passed: plan, lavapipe, build-linux-arm64, both harnesses, the gate on linux-arm64, linux-x86_64 and win-x86_64, host-gate, leaf-diff and publish.

- [host-gate](https://github.com/ThePhaseless/firefox_antidetect_patch/actions/runs/46066665864/job/140750886849): upstream's host gate from wrapper `v0.47.1`, run on the arm64 dump beside upstream's own firefox-58 x86 archives. Result: `HOST GATE OK: 0 failures`.
- [leaf-diff](https://github.com/ThePhaseless/firefox_antidetect_patch/actions/runs/46066665864/job/140750886883): every leaf of the linux-arm64 dump against the linux-x86_64 dump, same seeds and DPRs. Result: 6 visits (DPR 1.0 and 1.5, seeds 11, 12 and 13), 98616 checked leaves equal, 0 failures.
- [lavapipe-harness](https://github.com/ThePhaseless/firefox_antidetect_patch/actions/runs/46066665864/job/140739093262): WebGPU compute and render bytes from this run's lavapipe library on Neoverse-N2 against upstream's x86 library on an AMD EPYC 7763. All three render targets are equal. Compute is equal except for 111 NaN words, which carry each CPU's default NaN (see Not covered). The same harness on the previous release's library found 14560 compute words and every render target different.
- [fft-harness](https://github.com/ThePhaseless/firefox_antidetect_patch/actions/runs/46066665864/job/140738219194): WebAudio's FFT on both architectures. The aarch64 output equals the x86 AVX2 and FMA3 codelets'.

The release keeps the output and the full logs of the two gate jobs, because run logs expire: [host-gate.txt](https://github.com/ThePhaseless/firefox_antidetect_patch/releases/download/firefox-58-arm64/host-gate.txt), [host-gate.log](https://github.com/ThePhaseless/firefox_antidetect_patch/releases/download/firefox-58-arm64/host-gate.log), [leaf-diff.txt](https://github.com/ThePhaseless/firefox_antidetect_patch/releases/download/firefox-58-arm64/leaf-diff.txt), [leaf-diff.log](https://github.com/ThePhaseless/firefox_antidetect_patch/releases/download/firefox-58-arm64/leaf-diff.log) and [exceptions.diff](https://github.com/ThePhaseless/firefox_antidetect_patch/releases/download/firefox-58-arm64/exceptions.diff).

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

The gate, the leaf diff and the two harnesses measure only what their scenes draw and read. The fork makes no claim about the following:

- NaN bit patterns. A NaN that an operation creates (`inf - inf`, or `mod` by zero in a shader) is the CPU's default NaN: `ffc00000` on x86, with the sign bit set, and `7fc00000` on aarch64. A page can read it back as bits through WebGPU compute. The lavapipe harness finds it in 111 results of `mod()` by a subnormal, which flushes to zero. It counts exactly that pair and fails on anything else. Plain JavaScript shows the same: `Infinity - Infinity`, computed at runtime and stored in a `Float64Array`, reads back through a `Uint8Array` as `[0,0,0,0,0,0,248,255]` on x86 and `[0,0,0,0,0,0,248,127]` on arm64 (`Float32Array`: `[0,0,192,255]` and `[0,0,192,127]`), in the interpreter and in the JIT. SpiderMonkey keeps the hardware's NaN on purpose. Matching it would mean rewriting NaN results in lavapipe's JIT and in SpiderMonkey, code no upstream patch touches, so the fork leaves it.
- WebGPU outside the lavapipe harness's shaders. The harness holds 60 float operations, interpolated varyings, derivatives, trilinear and bilinear filtering, blending and subnormal `min`/`max` to byte equality. No other shader, texture format or sampler mode is checked.
- JIT timing.
- Decoded audio bits (`decodeAudioData`), measured in [run 46063377712](https://github.com/ThePhaseless/firefox_antidetect_patch/actions/runs/46063377712). MP3, Vorbis, FLAC and WAV decode to the same bits at the clip's own sample rate. The last bits differ (at most about 5e-7) in three cases:
  - whenever the decode resamples: x86 compiles the Speex resampler's `resample_sse.c`, and aarch64 runs its scalar loop (`media/libspeex_resampler/src/moz.build` enables NEON only for 32-bit arm);
  - for Opus at any rate: libopus has aarch64 NEON code for the inverse MDCT, the comb filter and de-emphasis, where x86 runs C and SSE;
  - for AAC, which Firefox decodes with the host's own libavcodec, not engine code.

  No upstream patch touches these paths, so the fork leaves them.
- The six blend modes that go through x86's approximate `RCPPS` reciprocal: `color-dodge`, `color-burn`, `hue`, `saturation`, `color` and `luminosity`. The gate's composite scenes draw all six (`control.composite.*`), and they are equal between the Linux legs there. Other inputs are unproven, because x86's `RCPPS` result depends on the CPU vendor.
- Skia's `rcp_precise` and `rsqrt` stages. x86 AVX2 uses `RCPPS` plus one fused Newton step and `RSQRTPS`; NEON uses `vrecpe` plus two `vrecps` steps and `vrsqrte` plus one step. They are reached by perspective transforms and SkSL `inverse()` of a 2x2 matrix, which canvas 2D cannot reach.
- Only one arm CPU model was tested: Neoverse-N2, GitHub's `ubuntu-24.04-arm` runner. In the release run the x86 gate legs ran on AMD EPYC 9V74 (Linux) and 7763 (Windows). Earlier runs on Intel Xeon Platinum 8573C and 6975P-C and AMD EPYC 9V45 gave the same results.
- Android, macOS and Windows on aarch64 are not built.
- Constant expressions that LLVM or Mesa fold at shader compile time with the host's libm (for example `sin` of a constant). The harness feeds only runtime inputs.

## Using the engine

The core's packaged seal has no linux-arm64 asset and lists arm64 as retired after firefox-55. A seal file that has the arm64 entry gets past that. The release's `seal.json` has every field and both x86 entries of upstream's firefox-58 seal unchanged (the publish job asserts it), plus this entry:

```json
"firefox-159.0-stealth-linux-arm64.tar.gz": {"arch": "arm64", "build_id": "20261108115355", "entry_rel": "firefox", "omni_sha256": "e745190aead37a0dbb6e9c5aa59be1136871ced7935d706bec7be221a76316c4", "platform": "linux", "sha256": "49bd7233b290c5d8ac7487e36adba22272f401c13abbef084530b20b5f27e61b", "size": 267681276}
```

The core downloads only from upstream's release URL, so the engine has to be in place before it looks. Point `INVISIBLE_PLAYWRIGHT_ENGINE_DIR` at a directory holding the extracted archive under `firefox-58_159.0_20261108115355/` (the core's content-keyed name, `<tag>_<upstream_version>_<build_id>` from the seal), and `INVISIBLE_SEAL_FILE` at the seal. The archive has `./firefox` and `./application.ini` at its root. The first `invisible_playwright fetch` adopts the tree and writes its stamp, `.invisible-seal.json`, into it (it needs write access to that directory once), and no download happens. After that, a user without write access gets stamp hits. Each process prints `invisible-core: substituted seal in effect: …` once on stderr.

The seal's `source_commit` is upstream's, because the seal schema has no field for an overlay. The arm64 binary is that commit plus `arm64/patches` at the commit in the release's `fork-commit.txt`; the release notes say so too.

### Byparr

A design for Byparr's Dockerfile, the form its arm64 pull request uses (amd64 keeps the packaged seal and upstream's download):

```dockerfile
FROM base AS engine-amd64

FROM base AS engine-arm64
ARG ARM64_ENGINE_URL=https://github.com/ThePhaseless/firefox_antidetect_patch/releases/download/firefox-58-arm64
ARG ARM64_SEAL_SHA256=cf5256b2c7f54fc4b496fffc77e853410c683f3bee8b0afaf92075c4d4f03f80
ARG ARM64_ARCHIVE_SHA256=49bd7233b290c5d8ac7487e36adba22272f401c13abbef084530b20b5f27e61b
ARG ARM64_ENGINE_TREE=firefox-58_159.0_20261108115355
ENV INVISIBLE_SEAL_FILE=/opt/invisible/seal.json \
    INVISIBLE_PLAYWRIGHT_ENGINE_DIR=/opt/invisible/engine
RUN mkdir -p "/opt/invisible/engine/$ARM64_ENGINE_TREE" \
 && curl -fsSL --retry 3 --retry-all-errors -o /opt/invisible/seal.json "$ARM64_ENGINE_URL/seal.json" \
 && curl -fsSL --retry 3 --retry-all-errors -o /tmp/engine.tar.gz "$ARM64_ENGINE_URL/firefox-159.0-stealth-linux-arm64.tar.gz" \
 && echo "$ARM64_SEAL_SHA256  /opt/invisible/seal.json" | sha256sum -c - \
 && echo "$ARM64_ARCHIVE_SHA256  /tmp/engine.tar.gz" | sha256sum -c - \
 && tar xzf /tmp/engine.tar.gz --no-same-owner -C "/opt/invisible/engine/$ARM64_ENGINE_TREE" \
 && rm /tmp/engine.tar.gz

# TARGETARCH is predefined in the global scope, so FROM can use it
FROM engine-${TARGETARCH} AS app
# ... the existing app stage, with this check right after `uv sync`:
RUN if [ -n "${INVISIBLE_SEAL_FILE:-}" ]; then uv run python -c 'import os, sys; from invisible_core.seal import load_seal, packaged_seal_path; p, e = load_seal(packaged_seal_path()), load_seal(os.environ["INVISIBLE_SEAL_FILE"]); k = lambda s: (s.tag, s.upstream_version, s.source_commit); k(p) == k(e) or sys.exit(f"invisible-core is sealed to {p.tag} ({p.upstream_version}, {p.source_commit}) but the arm64 engine seal is {e.tag} ({e.upstream_version}, {e.source_commit}): publish a matching arm64 release in ThePhaseless/firefox_antidetect_patch and update the ARM64_* args")'; fi
# ... and its root-time `uv run python -m invisible_playwright fetch` adopts and stamps
# /opt/invisible/engine at build time
```

- `ARM64_ARCHIVE_SHA256` is the `sha256` of the arm64 entry in the seal. Both values come from the release's `checksums.txt`; a new fork release means updating both.
- The check after `uv sync` stops a lock bump from pairing a newer core with this engine. Without it, a Renovate bump that moves `invisible-playwright` and `invisible-core` to firefox-59 still builds an arm64 image that runs core 59 on engine 58, while amd64 gets engine 59. The check compares the locked core's packaged seal (`tag`, `upstream_version`, `source_commit`) with the fork's seal and fails the build on any difference. To fix it, publish a fork release for the new tag and update the `ARM64_*` values.
- The base stage has curl and coreutils but no python3, so both downloads are checked with `sha256sum -c`.
- Extract straight into `firefox-58_159.0_20261108115355`. A legacy `firefox-58` tree written in an earlier image layer cannot be renamed to that name on overlayfs (EXDEV), so the core stamps the wrong directory, adopts again at every start, and fails with `PermissionError` as uid 1000.
- The engine sits in `/opt/invisible/engine`, outside `/cache`, so a volume or tmpfs over `/cache` cannot hide it. `/cache` keeps only machine state (geoip, fonts) and its existing `chmod -R a+rwX`.
- Both variables stay set at runtime. Without `INVISIBLE_SEAL_FILE` the core refuses arm64 as a retired leg.
- The `devcontainer` stage is left as it is. It runs `invisible_playwright fetch` without the seal file, so on arm64 it fails as it does today.

The adoption was checked on an aarch64 host by building Byparr's own Dockerfile from that pull request (base `ubuntu:26.04`, `invisible-core 58.56.0`, `invisible-playwright 0.47.1`). The files came from this release's URLs, with its two hashes as build arguments. Both files passed `sha256sum -c`, and the seal check passed. The root-time `fetch` printed `adopted the engine already cached at /opt/invisible/engine/firefox-58_159.0_20261108115355 ... no download needed`. In the built image, uid 1000 cannot write to `/opt/invisible`, which root owns, and still got that tree's `firefox` from both `fetch` and `ensure_binary()`. With a seal whose `tag` was changed to firefox-59, the seal check exited 1.

## License

The fork's own changes are under 0BSD; see [LICENSE](LICENSE) for the scope. Mozilla files stay under MPL-2.0, and patch hunks to Skia, ffvpx and Mesa files keep those projects' licenses. Upstream's own code is not relicensed.
