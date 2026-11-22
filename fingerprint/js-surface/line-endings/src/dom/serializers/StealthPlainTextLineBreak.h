/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_dom_StealthPlainTextLineBreak_h
#define mozilla_dom_StealthPlainTextLineBreak_h

// The default plain-text line break is Windows' on every build: a page reads it
// from getSelection().toString() across two blocks, "\r\n" on a Windows
// Firefox and "\n" on Linux [B294].
//
// DetermineLineBreak in nsPlainTextSerializer.cpp passes this literal to
// AssignLiteral on its platform/default branch, where Mozilla's text has
// NS_ULINEBREAK (u"\015\012" on Windows: the same literal). The other three
// branches (flags asking for CR, LF or CRLF) are untouched. The serializer also
// backs other plain-text output (copy as plain text): the effect is the one the
// hook has always had.
//
// Header-only: its one includer is nsPlainTextSerializer.cpp. Do not include it
// from another translation unit.
#define STEALTH_NATIVE_ULINEBREAK u"\r\n"

#endif  // mozilla_dom_StealthPlainTextLineBreak_h
