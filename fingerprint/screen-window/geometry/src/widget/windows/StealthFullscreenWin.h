/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_widget_StealthFullscreenWin_h
#define mozilla_widget_StealthFullscreenWin_h

// Windows keeps a fullscreen window on the HOST's monitor twice over, after
// nsIWidget::InfallibleMakeFullScreen asked for the declared rectangle
// (StealthFullscreen.h): nsWindow::OnWindowPosChanging forces every move and
// resize of a fullscreen window to the monitor's rect (bug 1482920), and
// DefWindowProc clamps the size to MINMAXINFO.ptMaxTrackSize, about the
// monitor's size. Both decide from the host; in fullscreen the window is the
// declared screen instead. Each does nothing with the engine off or outside
// fullscreen, and reads the size mode from the widget itself. Included by
// nsWindow.cpp.
//
// nsWindow::OnWindowPosChanging calls the hold between Mozilla's fullscreen
// block and the DWM block.

#include <windows.h>

class nsIWidget;

namespace mozilla::widget {

void StealthHoldDeclaredFullscreen(nsIWidget& aWidget, WINDOWPOS* aPos);
// aLParam is the lParam of WM_GETMINMAXINFO: a MINMAXINFO*.
void StealthDeclaredFullscreenTrackSize(nsIWidget& aWidget, LPARAM aLParam);

}  // namespace mozilla::widget

#endif  // mozilla_widget_StealthFullscreenWin_h
