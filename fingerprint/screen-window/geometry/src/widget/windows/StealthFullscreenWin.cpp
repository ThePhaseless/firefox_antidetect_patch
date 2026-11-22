/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#include "StealthFullscreenWin.h"

#include "StealthFullscreen.h"
#include "nsIWidget.h"

namespace mozilla::widget {

void StealthHoldDeclaredFullscreen(nsIWidget& aWidget, WINDOWPOS* aPos) {
  const bool fullscreen = aWidget.SizeMode() == nsSizeMode_Fullscreen;
  Maybe<LayoutDeviceIntRect> declared;
  if (fullscreen) {
    declared = StealthDeclaredFullscreenDeviceRect(aWidget);
  }
  int32_t x = aPos->x, y = aPos->y, cx = aPos->cx, cy = aPos->cy;
  StealthHeldFullscreenPosition(
      declared, fullscreen, !(aPos->flags & SWP_NOMOVE), !(aPos->flags & SWP_NOSIZE),
      &x, &y, &cx, &cy);
  aPos->x = x;
  aPos->y = y;
  aPos->cx = cx;
  aPos->cy = cy;
}

void StealthDeclaredFullscreenTrackSize(nsIWidget& aWidget, LPARAM aLParam) {
  MINMAXINFO* mmi = reinterpret_cast<MINMAXINFO*>(aLParam);
  const bool fullscreen = aWidget.SizeMode() == nsSizeMode_Fullscreen;
  Maybe<LayoutDeviceIntRect> declared;
  if (fullscreen) {
    declared = StealthDeclaredFullscreenDeviceRect(aWidget);
  }
  int32_t w = mmi->ptMaxTrackSize.x, h = mmi->ptMaxTrackSize.y;
  StealthFullscreenMaxTrackSize(declared, fullscreen, &w, &h);
  mmi->ptMaxTrackSize.x = w;
  mmi->ptMaxTrackSize.y = h;
}

}  // namespace mozilla::widget
