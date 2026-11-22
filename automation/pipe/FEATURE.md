# automation/pipe

Category: juggler
Prefs: none read directly
Test: wrapper tests/test_first_launch_from_a_new_path.py (test_the_first_launch_from_a_new_path_works; Windows, red on engines before firefox-27 where the launcher does not forward the pipe) and every Windows wrapper e2e (they all launch with --juggler-pipe)

## What it does

The browser is driven over a Juggler pipe. Windows only, and only with
`--juggler-pipe` on the command line. Two steps:

1. `wmain` (toolkit/xre/nsWindowsWMain.cpp, textually included by the bootstrap
   code of firefox.exe, the plugin/content process main and xpcshell) calls
   `StealthJugglerPipeStdio`: when PW_PIPE_READ is not set yet, it publishes the
   inherited CRT descriptors 3 and 4 (the pipe the automation client created,
   passed through the Node.js stdio array) as the decimal OS handle values in
   PW_PIPE_READ and PW_PIPE_WRITE. It runs before the launcher handoff.
2. The launcher process (browser/app/winlauncher/LauncherProcessWin.cpp) calls
   `StealthAddJugglerPipeHandles` while it builds the child's attribute list: the
   handles come from PW_PIPE_READ / PW_PIPE_WRITE and from nowhere else, and
   are added as inheritable handles, so the pipe code in xul.dll
   (juggler/pipe/nsRemoteDebuggingPipe.cpp) can read and write them. Reading the
   CRT descriptors again here was a second resolution of the same fact and
   disagreed with the first: a parent that names the handles itself opens no
   descriptor 3, and `_get_osfhandle(3)` on a closed descriptor trips the CRT's
   invalid-parameter handler, killing the launcher with 0xC0000409 on the first
   launch from every new install path (the second launch found a launcher
   timestamp without a browser timestamp and disabled the launcher process).

   The values go through atoi without a check: text that is not a number becomes
   handle 0, which ProcThreadAttributes refuses. The return value of
   AddInheritableHandles is ignored, as for the standard handles. argv is not
   modified.

## Our files

- `browser/app/winlauncher/StealthJugglerPipe.h`: `StealthAddJugglerPipeHandles(int&, wchar_t**, ProcThreadAttributes&)`.
- `toolkit/xre/StealthPipeStdio.h`: `StealthJugglerPipeStdio(int, wchar_t**)`. Windows only, all inline (it is included into three bootstrap translation units).

## Hooks in Mozilla files

- `browser/app/winlauncher/LauncherProcessWin.cpp`:
  - registration: `#include "StealthJugglerPipe.h"` in a block of ours after `#include "../BrowserDefines.h"`.
  - anchor in mozilla::LauncherMain: `StealthAddJugglerPipeHandles(argc, argv, attrs);` right after `attrs.AddInheritableHandles(stdHandles);`: `attrs` is a local built in the middle of the function and must already hold the standard handles.
- `toolkit/xre/nsWindowsWMain.cpp`:
  - registration: `#include "StealthPipeStdio.h"` in a block of ours after `#include <windows.h>`.
  - anchor in wmain: `StealthJugglerPipeStdio(argc, argv);` right after `SetDllDirectoryW(L"");`. The design proposed the head of wmain (neither SanitizeEnvironmentVariables nor SetDllDirectoryW touches PW_PIPE_*); it stays where it is until that move has its pm approval.
