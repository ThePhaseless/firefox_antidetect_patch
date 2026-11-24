/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_dom_StealthNativeEOL_h
#define mozilla_dom_StealthNativeEOL_h

// Native line endings are Windows' on every build: the browser this one stands
// for is a Windows Firefox, and a page reads the platform from
// new Blob(['\n'], {endings: 'native'}).size, 2 there and 1 on Linux [B294].
//
// BlobSet::AppendUTF8String converts "\n" to "\r\n" for endings 'native' under
// this macro, where Mozilla's text has `#ifdef XP_WIN`. The macro is 1 on every
// build, not behind the engine gate and not behind a pref: as XP_WIN is on a
// Windows build, the code is the same one and the bytes are the same.
//
// Header-only: its one includer is BlobSet.cpp. Do not include it from another
// translation unit.
#define STEALTH_NATIVE_EOL_IS_CRLF 1

#endif  // mozilla_dom_StealthNativeEOL_h
