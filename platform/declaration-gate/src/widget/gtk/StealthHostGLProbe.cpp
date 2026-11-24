/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#include "GfxInfo.h"
#include "StealthGfxFeatureStatus.h"

#ifdef MOZ_BACKGROUNDTASKS
#  include "mozilla/BackgroundTasks.h"
#endif

namespace mozilla::widget {

// The early fire of Mozilla's host GL probe in XRE_mainStartup
// (GfxInfo::FireGLXTestProcess, outside the background-task mode) comes
// before the profile's preferences are read, where StealthNoHostGLProbe()
// refuses it: the declaration is not known yet. This is the same fire right
// after they are read (the hook in nsAppRunner). It stands where Mozilla's
// stands, for a GTK build (USE_GLX_TEST of toolkit/xre is defined for every
// GTK build). With the engine on it launches nothing and reads nothing from
// the host; with the engine off, stock Firefox, the probe starts at startup
// and has all of it before GfxInfo::GetData waits for it.
void StealthFireHostGLProbeIfStock(StealthHostGLProbeLauncher aLauncher) {
#ifdef MOZ_BACKGROUNDTASKS
  if (BackgroundTasks::IsBackgroundTaskMode()) {
    return;
  }
#endif
  if (gfx::StealthNoHostGLProbe()) {
    return;
  }
  (aLauncher ? aLauncher : GfxInfo::FireGLXTestProcess)();
}

}  // namespace mozilla::widget
