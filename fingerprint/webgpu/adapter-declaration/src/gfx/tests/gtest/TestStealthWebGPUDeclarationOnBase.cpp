/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The declared WebGPU adapter at the points where Firefox's own code meets it:
// the descriptor clamped to the host adapter on RequestDevice, the compositor's
// adapter LUID left zeroed when there is no compositor device, and WebGPU kept
// on when the bundled Vulkan driver is mapped.

#include <cstring>

#include "gfxPlatform.h"
#include "gtest/gtest.h"
#include "mozilla/Preferences.h"
#include "mozilla/ScopeExit.h"
#include "mozilla/dom/WebGPUBinding.h"
#include "mozilla/gfx/gfxVars.h"
#include "mozilla/webgpu/StealthWebGPUDeclaration.h"
#include "mozilla/webgpu/SupportedLimits.h"
#include "mozilla/webgpu/ffi/wgpu.h"
#include "nsString.h"

using namespace mozilla;
using namespace mozilla::webgpu;

namespace {

// The JS names, as Adapter.cpp's ToJsKey gives them. The test only needs a
// key per limit; using the real names keeps the specs readable.
nsDependentCSubstring Key(const Limit aLimit) {
  switch (aLimit) {
#define STEALTH_KEY(X, S) \
  case Limit::X: \
    return nsDependentCSubstring(S, sizeof(S) - 1);
    STEALTH_KEY(MaxTextureDimension1D, "maxTextureDimension1D")
    STEALTH_KEY(MaxTextureDimension2D, "maxTextureDimension2D")
    STEALTH_KEY(MaxTextureDimension3D, "maxTextureDimension3D")
    STEALTH_KEY(MaxTextureArrayLayers, "maxTextureArrayLayers")
    STEALTH_KEY(MaxBindGroups, "maxBindGroups")
    STEALTH_KEY(MaxBindGroupsPlusVertexBuffers, "maxBindGroupsPlusVertexBuffers")
    STEALTH_KEY(MaxBindingsPerBindGroup, "maxBindingsPerBindGroup")
    STEALTH_KEY(MaxDynamicUniformBuffersPerPipelineLayout,
      "maxDynamicUniformBuffersPerPipelineLayout")
    STEALTH_KEY(MaxDynamicStorageBuffersPerPipelineLayout,
      "maxDynamicStorageBuffersPerPipelineLayout")
    STEALTH_KEY(MaxSampledTexturesPerShaderStage, "maxSampledTexturesPerShaderStage")
    STEALTH_KEY(MaxSamplersPerShaderStage, "maxSamplersPerShaderStage")
    STEALTH_KEY(MaxStorageBuffersInVertexStage, "maxStorageBuffersInVertexStage")
    STEALTH_KEY(MaxStorageBuffersInFragmentStage, "maxStorageBuffersInFragmentStage")
    STEALTH_KEY(MaxStorageBuffersPerShaderStage, "maxStorageBuffersPerShaderStage")
    STEALTH_KEY(MaxStorageTexturesInVertexStage, "maxStorageTexturesInVertexStage")
    STEALTH_KEY(MaxStorageTexturesInFragmentStage, "maxStorageTexturesInFragmentStage")
    STEALTH_KEY(MaxStorageTexturesPerShaderStage, "maxStorageTexturesPerShaderStage")
    STEALTH_KEY(MaxUniformBuffersPerShaderStage, "maxUniformBuffersPerShaderStage")
    STEALTH_KEY(MaxUniformBufferBindingSize, "maxUniformBufferBindingSize")
    STEALTH_KEY(MaxStorageBufferBindingSize, "maxStorageBufferBindingSize")
    STEALTH_KEY(MinUniformBufferOffsetAlignment, "minUniformBufferOffsetAlignment")
    STEALTH_KEY(MinStorageBufferOffsetAlignment, "minStorageBufferOffsetAlignment")
    STEALTH_KEY(MaxVertexBuffers, "maxVertexBuffers")
    STEALTH_KEY(MaxBufferSize, "maxBufferSize")
    STEALTH_KEY(MaxVertexAttributes, "maxVertexAttributes")
    STEALTH_KEY(MaxVertexBufferArrayStride, "maxVertexBufferArrayStride")
    STEALTH_KEY(MaxInterStageShaderVariables, "maxInterStageShaderVariables")
    STEALTH_KEY(MaxColorAttachments, "maxColorAttachments")
    STEALTH_KEY(MaxColorAttachmentBytesPerSample, "maxColorAttachmentBytesPerSample")
    STEALTH_KEY(MaxComputeWorkgroupStorageSize, "maxComputeWorkgroupStorageSize")
    STEALTH_KEY(MaxComputeInvocationsPerWorkgroup, "maxComputeInvocationsPerWorkgroup")
    STEALTH_KEY(MaxComputeWorkgroupSizeX, "maxComputeWorkgroupSizeX")
    STEALTH_KEY(MaxComputeWorkgroupSizeY, "maxComputeWorkgroupSizeY")
    STEALTH_KEY(MaxComputeWorkgroupSizeZ, "maxComputeWorkgroupSizeZ")
    STEALTH_KEY(MaxComputeWorkgroupsPerDimension, "maxComputeWorkgroupsPerDimension")
#undef STEALTH_KEY
  }
  return nsDependentCSubstring();
}

}  // namespace

// Adapter::RequestDevice hands wgpu a descriptor clamped to the host adapter
// (StealthWebGPUClampToReal): the page may ask for a declared maximum the host
// lacks and still gets a device. Every "max" limit goes down to the host's,
// every "min" limit up to it, and the features are cut to the host's.
TEST(StealthWebGPUDeclaration, RequestDeviceIsClampedToTheRealAdapter)
{
  auto restore =
      MakeScopeExit([] { Preferences::ClearUser("zoom.stealth.fpp.hw_seed"); });
  ffi::WGPUAdapterInformation real = {};
  real.features = 0x5;
  SetLimit(&real.limits, Limit::MaxTextureDimension2D, 8192);
  SetLimit(&real.limits, Limit::MinUniformBufferOffsetAlignment, 64);
  const auto asked = [] {
    ffi::WGPUFfiDeviceDescriptor desc = {};
    desc.required_features = 0x7;
    SetLimit(&desc.required_limits, Limit::MaxTextureDimension2D, 16384);
    SetLimit(&desc.required_limits, Limit::MinUniformBufferOffsetAlignment,
             32);
    return desc;
  };

  // Engine on: the descriptor is the AND of the features, the lower "max" and
  // the higher "min".
  Preferences::SetInt("zoom.stealth.fpp.hw_seed", 7);
  ffi::WGPUFfiDeviceDescriptor desc = asked();
  StealthWebGPUClampToReal(desc, real, Key);
  EXPECT_EQ(desc.required_features, real.features);
  EXPECT_EQ(GetLimit(desc.required_limits, Limit::MaxTextureDimension2D),
            8192u);
  EXPECT_EQ(GetLimit(desc.required_limits, Limit::MinUniformBufferOffsetAlignment),
            64u);

  // Negative control, engine off: Firefox's descriptor is left as it is.
  Preferences::ClearUser("zoom.stealth.fpp.hw_seed");
  desc = asked();
  StealthWebGPUClampToReal(desc, real, Key);
  EXPECT_EQ(desc.required_features, asked().required_features);
  EXPECT_EQ(GetLimit(desc.required_limits, Limit::MaxTextureDimension2D),
            16384u);
  EXPECT_EQ(GetLimit(desc.required_limits, Limit::MinUniformBufferOffsetAlignment),
            32u);
}

#ifdef XP_WIN

// The server asks the GPU process for the compositor's adapter LUID
// (wgpu_parent_get_compositor_device_luid, dom/webgpu/ipc/WebGPUParent.cpp) into
// memory it has not initialised. Without a compositor device Firefox's code
// writes nothing, so what the server reads is whatever was there: the same
// call must give the same LUID whatever the memory held before. Without the
// zeroing a prefilled LUID stays prefilled where there is no compositor device
// (the CI runner has none), and the two calls differ.
TEST(StealthWebGPUAdapter, NoCompositorDeviceLeavesNoUninitialisedLuid)
{
  gfxPlatform::GetPlatform();
  ffi::WGPUFfiLUID fromZero = {};
  ffi::WGPUFfiLUID fromGarbage;
  memset(&fromGarbage, 0xA5, sizeof(fromGarbage));
  ffi::wgpu_parent_get_compositor_device_luid(&fromZero);
  ffi::wgpu_parent_get_compositor_device_luid(&fromGarbage);
  EXPECT_EQ(memcmp(&fromZero, &fromGarbage, sizeof(fromZero)), 0);
}

#endif  // XP_WIN

#if defined(XP_LINUX) && !defined(ANDROID) && defined(__x86_64__)

#  include <dlfcn.h>

#  include <string>

// gfxPlatform::InitWebGPUConfig calls StealthWebGPUPlatformInit: with the
// engine on the bundled driver is mapped under the loader's name and WebGPU
// stays as Firefox decided (it is turned off only when the driver cannot be
// mapped, never left to a host driver). Engine off: nothing is mapped here and
// the answer is Firefox's.
TEST(StealthWebGPUBundledVulkan, AllowWebGPUFollowsTheBundledVulkan)
{
  gfxPlatform::GetPlatform();  // brings gfxVars up
  const bool before = gfx::gfxVars::AllowWebGPU();
  auto restore = MakeScopeExit([before] {
    Preferences::ClearUser("zoom.stealth.fpp.hw_seed");
    gfx::gfxVars::SetAllowWebGPU(before);
  });

  // Negative control, engine off: Firefox's value is left alone.
  Preferences::ClearUser("zoom.stealth.fpp.hw_seed");
  gfx::gfxVars::SetAllowWebGPU(true);
  StealthWebGPUPlatformInit();
  EXPECT_TRUE(gfx::gfxVars::AllowWebGPU());

  // Engine on: the driver is ours, and WebGPU stays on.
  Preferences::SetInt("zoom.stealth.fpp.hw_seed", 7);
  gfx::gfxVars::SetAllowWebGPU(true);
  StealthWebGPUPlatformInit();
  EXPECT_TRUE(gfx::gfxVars::AllowWebGPU());
  void* byName = dlopen("libvulkan.so.1", RTLD_NOW | RTLD_NOLOAD);
  ASSERT_TRUE(byName);
  Dl_info info = {};
  ASSERT_TRUE(dladdr(dlsym(byName, "vkGetInstanceProcAddr"), &info));
  dlclose(byName);
  ASSERT_TRUE(info.dli_fname);
  EXPECT_NE(std::string(info.dli_fname).find("/lavapipe/libvulkan_lvp.so"),
            std::string::npos)
      << info.dli_fname;
}

#endif  // XP_LINUX && !ANDROID && __x86_64__
