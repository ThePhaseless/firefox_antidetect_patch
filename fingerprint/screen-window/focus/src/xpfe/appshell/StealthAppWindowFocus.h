/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// With zoom.stealth.focus.ignore_os_deactivation (B149) the window keeps its
// activation when the SYSTEM takes it away - another application, another
// session's window on the same display - and loses it only to this session's
// own windows, whose activation arrives as WindowActivated and lowers the
// window it replaces there, with the same blur a page sees in any Firefox.
//
// The window this one replaces is lowered first and with its own action id:
// the order and the ids a page's process sees are those of an ordinary
// switch. Left to WindowRaised, the lowering travels with the raise's id, the
// page's process has already given up its active window when the deactivation
// arrives, and document.hasFocus() turns false with no blur event.

#ifndef STEALTH_APPWINDOW_FOCUS_H_
#define STEALTH_APPWINDOW_FOCUS_H_

#include "mozilla/Attributes.h"
#include "mozilla/StaticPrefs_zoom.h"
#include "nsFocusManager.h"
#include "nsPIDOMWindow.h"

// AppWindow::WindowDeactivated: true when the pref is set, and Mozilla's
// deactivation body is then skipped.
inline bool StealthKeepsActivation() {
  return mozilla::StaticPrefs::zoom_stealth_focus_ignore_os_deactivation();
}

// AppWindow::WindowActivated, right before Mozilla's raise: lowers the window
// that is active now (when it is another one), with its own action id.
MOZ_CAN_RUN_SCRIPT inline void StealthLowerActiveWindow(
    nsPIDOMWindowOuter* aWindow, nsFocusManager* aFm) {
  if (!mozilla::StaticPrefs::zoom_stealth_focus_ignore_os_deactivation()) {
    return;
  }
  nsCOMPtr<nsPIDOMWindowOuter> active = aFm->GetActiveWindow();
  if (active && active != aWindow) {
    aFm->WindowLowered(active, nsFocusManager::GenerateFocusActionId());
  }
}

#endif  // STEALTH_APPWINDOW_FOCUS_H_
