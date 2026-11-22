# automation/file-chooser

Category: juggler
Prefs: none read directly
Test: wrapper:tests/test_file_chooser.py::test_expect_file_chooser_receives_the_event (control: test_without_interception_the_file_inputs_remain_normal; also test_the_chosen_files_arrive_at_the_page, node:juggler/tests/docshell_settings_follow_every_local_docshell.test.mjs#a setting reaches the root and the local iframe at once, and a frame of another process is skipped)

## What it does

When the automation asked to intercept the file chooser
(`Page.setInterceptFileChooserDialog`, written by `juggler/content/main.js` to
`nsIDocShell.fileInputInterceptionEnabled`), `HTMLInputElement::InitFilePicker`
returns before the native dialog opens, without touching `mPickerRunning` (no
picker is running, and saying otherwise would refuse the next one: "Just one
nsIFilePicker is allowed"). The JS side gets the element through the
`file-input-picker-opening` notification that `InitFilePicker` fires just above
(`juggler/content/PageAgent.js`), with the element as its subject. Until
2026-08-25 nothing read the flag, so `expect_file_chooser()` hung while a real
"Open file" window opened on the desktop and took the focus.

## Hooks in Mozilla files

In `dom/html/HTMLInputElement.cpp`, one line each; the logic is in
`dom/html/StealthFileChooser.h` (own file, header only):

- Registration: `#include "StealthFileChooser.h"` in a block of ours after
  Mozilla's includes (it includes `nsIDocShell.h`; Mozilla's file has no such
  include of its own).
- Anchor, in `HTMLInputElement::InitFilePicker`, right after the
  `if (obs) { obs->NotifyObservers(..., "file-input-picker-opening", nullptr); }`
  block and before the `!oldFiles.IsEmpty()` branch:
  `if (StealthFileChooserIntercepted(doc)) return NS_OK;`.
  `StealthFileChooserIntercepted` receives the `doc` local of Mozilla's
  function and reads the flag from its docshell (false with no docshell). It is an anchor and not a guard at the
  top of the function because a guard there would skip the notification the
  automation listens to and the file picker setup before it; there is no value
  to wrap.

## Test

`wrapper:tests/test_file_chooser.py::test_expect_file_chooser_receives_the_event`
fails without the hook (the native dialog opens and `expect_file_chooser()`
hangs) and `test_the_chosen_files_arrive_at_the_page` covers the files handed
to the page. Negative control:
`test_without_interception_the_file_inputs_remain_normal`: with the
interception off the inputs keep their native behaviour. The node test
`docshell_settings_follow_every_local_docshell.test.mjs` fixes that the flag
reaches every local docshell.
