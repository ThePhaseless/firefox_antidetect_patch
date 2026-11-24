/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// When the automation asked to intercept the file chooser, InitFilePicker
// returns before the native dialog opens, without touching mPickerRunning (no
// picker is running, and saying otherwise would refuse the next one: "Just
// one nsIFilePicker is allowed"). The JS side gets the element through the
// notification that InitFilePicker fires just above the hook
// (juggler/content/PageAgent.js), with the element as its subject, which is
// all it needs.
//
// The flag is written by juggler/content/main.js on request of
// `Page.setInterceptFileChooserDialog` and lives on the docshell
// (nsIDocShell.fileInputInterceptionEnabled). Before it was read here nothing
// read it, so `expect_file_chooser()` hung while a real "Open file" window
// opened on the desktop and took the focus.
//
// The hook is an anchor after the notification block, not a guard at the top
// of InitFilePicker: a guard there would skip the notification the automation
// listens to and the setup of the file picker before it.

#ifndef STEALTH_FILE_CHOOSER_H_
#define STEALTH_FILE_CHOOSER_H_

#include "mozilla/dom/Document.h"
#include "nsIDocShell.h"

namespace mozilla::dom {

// True when the docshell of the document InitFilePicker works on (the `doc`
// local of Mozilla's function, which the hook passes) intercepts the file
// chooser. False with no docshell.
inline bool StealthFileChooserIntercepted(const Document* aDoc) {
  bool intercept = false;
  if (nsIDocShell* docShell = aDoc->GetDocShell()) {
    docShell->GetFileInputInterceptionEnabled(&intercept);
  }
  return intercept;
}

}  // namespace mozilla::dom

#endif  // STEALTH_FILE_CHOOSER_H_
