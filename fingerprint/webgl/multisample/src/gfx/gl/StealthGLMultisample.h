/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef GFX_GL_STEALTH_GL_MULTISAMPLE_H_
#define GFX_GL_STEALTH_GL_MULTISAMPLE_H_

#include <bitset>

#include "GLContext.h"

namespace mozilla::gl {

// Whether a context multisamples, decided by the declaration, not by the
// host's renderer. aDriverSupports is the feature as the driver reports it,
// before Mozilla's driver workarounds in GLContext::InitImpl ran.
bool StealthDeclaredMultisample(bool aDriverSupports);

// GLContext::InitImpl, right after InitFeatures(): keeps the feature as the
// driver reports it (aReported is GLContext::mStealthReportedMultisample), before
// Mozilla's driver workarounds run.
void StealthNoteReportedMultisample(const GLContext* aGl, bool& aReported);

// GLContext::InitImpl, right after the driver-workaround block: puts the
// feature back when the declaration says the context multisamples
// (aFeatures is GLContext::mAvailableFeatures). Only the feature bit, as it
// always was: the extension bits the workaround cleared stay cleared.
void StealthRestoreMultisample(
    std::bitset<size_t(GLFeature::EnumMax)>& aFeatures, bool aReported);

}  // namespace mozilla::gl

#endif  // GFX_GL_STEALTH_GL_MULTISAMPLE_H_
