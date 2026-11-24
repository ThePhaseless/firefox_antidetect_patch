/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef GFX_STEALTH_GFX_FEATURE_STATUS_H_
#define GFX_STEALTH_GFX_FEATURE_STATUS_H_

// The graphics feature decisions (nsIGfxInfo::GetFeatureStatus) come from the
// declaration, zoom.stealth.gfx.feature_status: the status retail Firefox on
// Windows 11 gives each feature for the persona's real GPU, measured by the
// core. Mozilla decides them from the host's adapter (vendor, device, driver,
// OS): on a Windows VM or a GPU-less host it blocks WebGL2, accelerated ANGLE,
// WebGPU, and a page reads the machine through what is missing. Every
// decision, in every process and on every host, is the declared one.
//
// Format: "NAME|STATUS[|FAILURE],..." with NAME the id of a live feature in
// widget/GfxInfoFeatureDefs.inc (WEBGL_OPENGL, GL_NORM16_TEXTURES, ...),
// STATUS a decimal nsIGfxInfo status and FAILURE the retail failure id. Every
// live feature exactly once: a feature Mozilla adds at a port makes the engine
// refuse until the core has measured it.

#include "mozilla/Maybe.h"
#include "nsString.h"
#include "nsTArray.h"

class nsIGfxInfo;

namespace mozilla::gfx {

struct StealthGfxFeatureEntry {
  int32_t mStatus = 0;
  nsCString mFailureId;
};

// One slot per nsIGfxInfo feature id; Nothing() for ids outside the live set.
using StealthGfxFeatureTable = nsTArray<Maybe<StealthGfxFeatureEntry>>;

// Parses and validates a declaration. False with the reason in aError when it
// breaks any rule (see the .cpp); aTable is then left empty.
bool StealthParseGfxFeatureStatus(const nsACString& aDeclaration,
                                  StealthGfxFeatureTable& aTable,
                                  nsACString& aError);

// The answer for one feature from a parsed table. On builds where the only
// WebGL path is native GL (GTK), WEBGL_OPENGL answers the declared WEBGL
// entry, because on Windows that path is ANGLE and WEBGL_OPENGL gates a path
// retail never takes. Nothing about the host is probed (see
// StealthNoHostGLProbe). False for an id outside the live set.
bool StealthAnswerGfxFeature(const StealthGfxFeatureTable& aTable,
                             int32_t aFeature, nsACString& aFailureId,
                             int32_t* aStatus);

// The hook in GfxInfoBase::GetFeatureStatus. False when the engine is off
// (stock Firefox) or the id is outside the live set: Mozilla's path runs.
// Content and GPU processes answer from the parent's feature cache, which the
// parent built from the declaration; every other process parses the pref once
// and refuses to run when it is missing or malformed.
bool StealthGfxDeclaredStatus(nsIGfxInfo* aGfxInfo, int32_t aFeature,
                              nsACString& aFailureId, int32_t* aStatus);

// True when the declaration decides: the downloadable blocklist is not
// evaluated and writes no gfx.blacklist.* pref into the profile.
bool StealthGfxDeclarationActive();

// The suggested driver version (about:support): empty while declared. True
// when it answered.
bool StealthGfxSuggestedDriverVersion(nsAString& aVersion);

#ifdef MOZ_WIDGET_GTK
// Linux: glxtest, the child that dlopens the HOST's libEGL, libGL, libpci and
// libdrm to read its adapter, is removed from our build, not switched off by a
// pref. Our own GL (llvmpipe behind EGL, in the package) is the only GL, so a
// host probe has no use, and what it reported (adapter, driver, DRM device,
// PCI ids, uname) is host data no page may see; its 4 s timeout or a failure
// used to disable WebGL for the whole session. True with the engine on, and
// before the profile's preferences are read (StealthUserPrefsRead): the early
// fire in nsAppRunner (XRE_mainStartup) and anything that would reach GfxInfo
// before XRE_mainRun's InitializeUserPrefs (a profile reset or migration
// window, a temporary XPCOM of the profile manager) cannot tell a declared
// launch, since StealthEngineActive() still reads the defaults. With the
// engine off (stock Firefox) false after it: GfxInfo::GetData then fires
// Mozilla's glxtest itself, as it does when nothing fired it in advance.
bool StealthNoHostGLProbe();

// What GfxInfo::GetData fills in without glxtest: the test type is EGL (our
// own GL; keeps gfxPlatformGtk's X11_EGL decision on the declared status), no
// glxtest error, no adapter RAM, and the two display-protocol flags from the
// display connection. Every adapter, driver, DRM and PCI field stays empty.
// True with the engine on or before the profile's preferences are read (the
// caller returns); false with the engine off after them, and Mozilla's GetData
// reads its glxtest as stock Firefox does.
bool StealthFillGtkGfxInfoWithoutHost(nsACString& aTestType,
                                      bool& aGlxTestError,
                                      uint32_t& aAdapterRAM, bool& aIsWayland,
                                      bool& aIsXWayland);
#endif

// The profile's preferences have been read: set once by the hook in
// nsAppRunner right after XRE_mainRun's InitializeUserPrefs, where the
// declaration (zoom.stealth.fpp.hw_seed and the rest) arrives. Before it,
// StealthEngineActive() reads only the defaults and cannot tell a declared
// launch from stock Firefox.
void StealthMarkUserPrefsRead();
bool StealthUserPrefsRead();
// Tests only: a gtest runs in XRE_mainStartup, before that hook.
void StealthSetUserPrefsReadForTesting(bool aRead);

// Tests only: forget the parsed declaration so the next call parses again.
void StealthResetGfxFeatureStatusForTesting();

}  // namespace mozilla::gfx

namespace mozilla::widget {

#ifdef MOZ_WIDGET_GTK
// Linux: Mozilla fires its host GL probe (GfxInfo::FireGLXTestProcess) at
// once in XRE_mainStartup, before the profile's preferences are read, where
// StealthNoHostGLProbe() cannot tell stock Firefox from a declared launch and
// so never lets it start. With the engine off (stock Firefox) the probe then
// began only inside GfxInfo::GetData, with its 4 s timeout, and under load
// it failed and left WebGL off for the session. This is the hook right after
// the preferences are read (nsAppRunner): with the engine off and outside the
// background-task mode it fires the probe, as Mozilla does at startup; with
// the engine on, or before the preferences are read, it does nothing. The
// launcher is GfxInfo::FireGLXTestProcess unless a test passes its own, so a
// gtest observes the launch without spawning the host's glxtest.
using StealthHostGLProbeLauncher = bool (*)();
void StealthFireHostGLProbeIfStock(
    StealthHostGLProbeLauncher aLauncher = nullptr);
#else
inline void StealthFireHostGLProbeIfStock() {}
#endif

}  // namespace mozilla::widget

#endif  // GFX_STEALTH_GFX_FEATURE_STATUS_H_
