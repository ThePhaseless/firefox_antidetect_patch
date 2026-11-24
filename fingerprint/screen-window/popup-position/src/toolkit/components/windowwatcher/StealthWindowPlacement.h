/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef TOOLKIT_COMPONENTS_WINDOWWATCHER_STEALTHWINDOWPLACEMENT_H_
#define TOOLKIT_COMPONENTS_WINDOWWATCHER_STEALTHWINDOWPLACEMENT_H_

#include "Units.h"

class nsIBaseWindow;

namespace mozilla {

/**
 * Called by SizeOpenedWindow (nsWindowWatcher.cpp) right after it has set
 * `positionSpecified` from the page's features. left and top were taken from
 * the features before; the statements between them and this call only set the
 * local width and height, which this function neither reads nor writes.
 *
 * A window a page opens without left/top is born at the declared default
 * position. Writes aLeft only when !aHasLeft and aTop only when !aHasTop, and
 * then sets aPositionSpecified (the caller treats the position as specified);
 * nothing written and nothing read from the window for a chrome caller, or when
 * the engine is off.
 */
void StealthPlacePopupAtDefault(bool aIsCallerChrome,
                                nsIBaseWindow* aTreeOwnerAsWin, bool aHasLeft,
                                bool aHasTop, DesktopIntCoord& aLeft,
                                DesktopIntCoord& aTop,
                                bool& aPositionSpecified);

}  // namespace mozilla

#endif  // TOOLKIT_COMPONENTS_WINDOWWATCHER_STEALTHWINDOWPLACEMENT_H_
