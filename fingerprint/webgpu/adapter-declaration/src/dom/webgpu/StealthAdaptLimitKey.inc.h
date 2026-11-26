/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// Included by Adapter.cpp at file scope, before the constructor of Adapter: the declaration of Adapter.cpp's own
// ToJsKey (a function with internal linkage, defined below the constructor), which the hook of the constructor names
// (StealthAdaptLimitKey<ToJsKey>) before its definition. It is only a declaration of a function that file defines, so it
// is not a header: another file that included it would declare a function of its own.

static std::string_view ToJsKey(const Limit limit);
