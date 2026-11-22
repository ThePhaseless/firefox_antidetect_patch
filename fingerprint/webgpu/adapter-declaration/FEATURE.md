# fingerprint/webgpu/adapter-declaration

Category: spoof
Prefs: zoom.stealth.webgpu.adapter, zoom.stealth.webgpu.features, zoom.stealth.webgpu.limits, zoom.stealth.fpp.hw_seed (the software adapter on Windows)
Test: gfx/tests/gtest/TestStealthWebGPUDeclaration.cpp (StealthWebGPUDeclaration.*, among them RequestDeviceIsClampedToTheRealAdapter (the descriptor sent to wgpu is clamped to the host adapter; engine off leaves it as Firefox builds it); StealthWebGPUBundledVulkan.AllowWebGPUFollowsTheBundledVulkan, Linux x86_64 (StealthWebGPUPlatformInit maps our driver and leaves AllowWebGPU as Firefox decided; engine off leaves it alone); StealthWebGPUAdapter.*, Windows only (among them NoCompositorDeviceLeavesNoUninitialisedLuid: the compositor LUID the server reads is the same whatever the memory held before the call): on the GPU-less CI runner the compositor search finds nothing and the adapter must be WARP, engine off keeps null, a found adapter is left alone). Wrapper e2e (tests/test_webgpu_adapter_is_declared_e2e.py: the page sees the declared features, limits and isFallbackAdapter, forceFallbackAdapter answers true, a requestDevice at a declared maximum succeeds; a declared GPU without Direct3D 12 resolves requestAdapter with null and an unknown featureLevel warns and resolves null as stock; tests/test_webgpu_external_texture_e2e.py: importExternalTexture exists on every OS). Host gate: navigator.gpu.requestAdapter() non-null with info.isFallbackAdapter false on the GPU-less Windows runner. Linux x86_64: StealthWebGPUBundledVulkan.* (the loader's name leads to our lavapipe, the adapter is ours at 128 bits and has every declared limit, no host libvulkan is mapped); scripts/ci/test_ci.py (the workflow builds and ships it, the library check). StealthWebGPUInstanceEnv.TheHostsVariablesDoNotReachTheInstance (Windows only): the wgpu instance flags with the host's WGPU_* variables set equal stock's with none set when the engine is on, and stock still reads them.

## What it does

On Windows the server answers null when the compositor's D3D12 adapter is not
among wgpu's, which is every host without a GPU (the Basic Render Driver
adapter is dropped by wgpu-hal, or there is no compositor device). With the
engine on, that search falling empty takes the software D3D12 adapter (WARP),
present on every Windows host, so a page gets an adapter as on retail with the
declared GPU; features, limits and isFallbackAdapter stay declared
(gfx/wgpu_bindings/src/stealth_webgpu_adapter.rs). The compositor LUID out
parameter is zeroed first, so a missing compositor device is no match rather
than uninitialised memory read by Mozilla's code.

The WebGPU adapter a page sees is declared by invisible_core, never read from the host. Firefox's
Adapter::Adapter hands the page the features and limits wgpu reports for the real adapter (D3D12 on
Windows, Vulkan on Linux, a CPU adapter on a Linux machine with no GPU), clamped only under
resistFingerprinting. Measured 2026-10-31 against retail Firefox 159 for Windows, headed: Linux
answered isFallbackAdapter true, one extra feature (clip-distances) and 14 different limits. Retail's
13 features and 35 limits were identical for an RTX 5080, an Intel iGPU and WARP on the same machine:
constants of Firefox's D3D12 backend, not of the GPU. So the core declares them once, and "none" for a
GPU without Direct3D 12 (requestAdapter resolves null, as on such a machine). isFallbackAdapter is true
only for an adapter asked for with forceFallbackAdapter, as retail's WARP answers.

What reaches wgpu stays real: RequestDevice reports the limits and features the page asked for, as
Firefox does, but the descriptor sent to wgpu is clamped to the host adapter, so asking for a
declared maximum the host lacks still gives a device.

The hook ceiling of gfx/tests/gtest/moz.build (owned by fingerprint/canvas/noise-projection) went
from 11 to 12 for the one line that registers this folder's gtest.

## Linux: our own Vulkan driver

WebGPU on Linux has only wgpu's Vulkan backend: with no Vulkan driver on the host
`requestAdapter()` answered null, and with the host's Mesa its version decided
limits and raster bytes. The driver ships in the package (`lavapipe/`, built in CI
by `scripts/ci/lavapipe_build.py` from pinned Mesa and LLVM, patched so no host
value reaches it: no environment, the x86-64 baseline, exact sqrt, fixed heap,
budget and threads, no udmabuf). There is no Vulkan loader: the library carries
the loader's SONAME and exports `vkGetInstanceProcAddr`, and
`StealthWebGPUPlatformInit` (gfxPlatform::InitWebGPUConfig, parent) maps it before
wgpu opens "libvulkan.so.1" by name. Fail closed: a host loader mapped first, a
missing file or a name that leads elsewhere turn WebGPU off. x86_64 only: arm64
ships without it and WebGPU answers null there.

The WebGPU server's wgpu instance does not read the host's environment: `wgpu_server_new` reads seven `WGPU_*` variables into its instance flags (`InstanceFlags::with_env()`), the only environment read reachable in a release build; with the engine on the flags are the ones built with no variable set (`gfx/wgpu_bindings/src/stealth_webgpu_env.rs`). The two `server.rs` hooks call modules declared by one `mod` line each at file level.

## Known defect

maxBindingsPerBindGroup on Linux (decided 2026-11-02 for firefox-55): retail on D3D12 reports u32::MAX; our lavapipe holds about 2^20 because it sizes a descriptor set layout by the highest binding number. A page binding at an index above that fails on Linux and not on retail. The gtest StealthWebGPUBundledVulkan.TheAdapterIsOursAndHoldsTheDeclaration lists it by name and fails on any other gap or when this one closes. The work that closes it: dense Vulkan binding indices per layout in wgpu-hal and in naga's SPIR-V output.

## Hooks in Mozilla files

- `dom/webgpu/Adapter.cpp`: the include in a block of ours after Mozilla's (registration); `if (StealthWebGPUDeclared()) return StealthWebGPUIsFallback(mParent.get());` first statement of `AdapterInfo::IsFallbackAdapter` (guard with a value, G15; the engine is on, and the answer is the note the request left for the adapter, false for one without a note); the forward declaration of `ToJsKey` (registration, G40: it is Adapter.cpp's own static, declared so the declaration is keyed by the names the page reads); `StealthWebGPUDeclareAdapter(...)` in `Adapter::Adapter` right after the `while (remainingFeatureBits)` loop (anchor: the loop fills the features from the host's adapter, the hook replaces them with the declared set, before `Core_features_and_limits` and the RFP clamp that Mozilla applies after; it cannot go first, the loop would fill them again, nor last, it would change the order with RFP; `aInfo` is shared with `mInfoInner`, which RequestDevice uses as the real adapter, so it is not changed at birth); `StealthWebGPUClampToReal(ffiDesc, *mInfoInner, ...)` in `Adapter::RequestDevice` after `ffiDesc.required_limits = deviceLimits;` (anchor: it changes the local `ffiDesc` that Mozilla passes to `wgpu_client_request_device` on the next line).
- `dom/webgpu/Instance.cpp`: the include; `if (StealthWebGPUNoAdapter(promise)) return promise.forget();` in `Instance::RequestAdapter` right after the power preference is computed (anchor with a guard, accepted by the pm: it must run after Mozilla's own checks (the rejections, the `JS::WarnUTF8` for `featureLevel` and `xrCompatible`, null for an unknown `featureLevel`), which a guard at the top would change for the page, and before `wgpu_client_request_adapter`, the request to the real adapter; `StealthWebGPUNoAdapter` resolves the promise with null when the declared GPU has no Direct3D 12 adapter, and refuses a declaration that is neither "d3d12" nor "none"); `StealthWebGPUNoteRequest(this, adapter_id, aOptions.mForceFallbackAdapter)` after `RawId adapter_id = ...` and before `EnqueueRequestAdapterPromise` (anchor: it needs `adapter_id`, and the Adapter constructor consumes the note when the answer arrives).
- `dom/webgpu/ipc/WebGPUParent.cpp` (Windows): `StealthWebGPUZeroLuid(aOutLuid);` first statement of `wgpu_parent_get_compositor_device_luid` (notice): the out parameter is zeroed before Mozilla's code fills it only when it finds the LUID, so a missing compositor device reads as no match, not as uninitialised memory; the include.
- `dom/webgpu/moz.build`: `EXPORTS.mozilla.webgpu += [...]` and `SOURCES += [...]` after the closing `]` of the lists (registration); non-unified because our file has file-static helpers with short names.
- `gfx/thebes/gfxPlatform.cpp`: the include; `mozilla::webgpu::StealthWebGPUPlatformInit();` in `gfxPlatform::InitWebGPUConfig` after the `if (!IsGfxInfoStatusOkay(FEATURE_WEBGPU_EXTERNAL_TEXTURE...)) {...}` block and before the force-disable `#if` (anchor: the preload fails when a host Vulkan loader is already mapped, so it stays after the gfxInfo call of the external texture, which could map one; it is not a wrap of `SetAllowWebGPU`). Linux's Vulkan driver is ours (see above). Declared exception (pm approved, G35): the line `#if !defined(XP_WIN) && !defined(XP_MACOSX) && 0` compiles out the force-disable of WebGPU external textures off Windows and macOS, because the engine presents Windows on every OS where the feature is on and the import runs on the shared-memory buffer path; restoring Mozilla's `#if` and wrapping `SetAllowWebGPUExternalTexture` is not provably identical (a user pref set to false, a gfxInfo blocklist).
- `gfx/wgpu_bindings/src/server.rs`: the two `mod` lines of our files at file level after the `use` block (registration; the `#[path]` is relative to the folder of the file, `gfx/wgpu_bindings/src`); `stealth_webgpu_env::without_host_env(&mut instance_flags);` after the `instance_flags` statement of `wgpu_server_new` (anchor; the `with_env()` of Mozilla reads the host's variables and the hook overwrites the result, listed in the series' findings); `stealth_webgpu_adapter::settle(global, &desc, adapter_id, &mut result);` after the Windows compositor-LUID block of the `RequestAdapter` message (anchor: it changes `result`, which Mozilla reads on the next statement).
- `modules/libpref/init/StaticPrefList.yaml`: `dom.webgpu.external-texture.enabled` takes `true` (Windows' value) on its own line in the `#else` branch (declared value: the pref has a mirror `once` and reads this default). The same file carries three hooks of network/proxy and network/doh (`network.proxy.type`, `network.trr.request_timeout_ms`, `network.trr.exclude-etc-hosts`); a file has one owner, and each of those folders carries its own.

## Our own files

- `dom/webgpu/StealthWebGPUDeclaration.cpp`
- `dom/webgpu/StealthWebGPUDeclaration.h`
- `gfx/tests/gtest/TestStealthWebGPUDeclaration.cpp`
- `gfx/wgpu_bindings/src/stealth_webgpu_adapter.rs`
- `gfx/wgpu_bindings/src/stealth_webgpu_env.rs`

External textures (2026-10-31, the host gate): retail Windows exposes GPUDevice.importExternalTexture
and it works; Linux had no such method, because dom.webgpu.external-texture.enabled defaults to false
off Windows and macOS, and with the pref on gfxPlatform::InitWebGPUConfig force-disables the feature
("not supported on this Operating System"). The pref takes Windows' value on its own line in
StaticPrefList.yaml, and the force-disable is compiled out (one rewritten line each, in
removed-budget.json); off Windows the import runs on the generic shared-memory buffer path.
The same file carries a second hook, of network/proxy: `network.proxy.type` defaults to 0 on Mozilla's own line (a file has one owner, so
the hunk is carried here; its feature, folder and test are network/proxy).
