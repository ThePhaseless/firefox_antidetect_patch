/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef widget_gtk_StealthOcclusion_h
#define widget_gtk_StealthOcclusion_h

#include "mozilla/StaticPrefs_zoom.h"

// Occlusion tracking on GTK/Linux (feature occlusion-tracking, B149).
//
// With zoom.stealth.widget.occlusion_tracking.enabled false, as the core
// declares it, a window that is fully covered stays visible to its page (the
// page does not see `hidden`), as on Windows where the same declaration turns
// occlusion tracking off. Measured on Xvfb: a second session's window made the
// first one's page `hidden` 4 times in 4 without it.
//
// nsWindow::OnVisibilityNotifyEvent wraps the condition of Mozilla's ternary
// (`aState == GDK_VISIBILITY_FULLY_OBSCURED`) in this function. The
// notification itself is still sent (NotifyOcclusionState(UNKNOWN) when this
// answers false), as before; a guard that returned early would skip it. The
// pref is read only when the window is fully obscured.
inline bool StealthOcclusionTracked(bool aObscured) {
  return aObscured &&
         mozilla::StaticPrefs::zoom_stealth_widget_occlusion_tracking_enabled();
}

#endif  // widget_gtk_StealthOcclusion_h
