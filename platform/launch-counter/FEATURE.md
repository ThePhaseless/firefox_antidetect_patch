# platform/launch-counter

Category: other
Prefs: none (the counter is mandatory: no preference gates it and none moves it)
Test: browser/components/tests/unit/test_stealth_launch_counter.js (xpcshell: test_sends_one_plain_get_to_the_fixed_address, test_old_prefs_neither_stop_it_nor_move_it, test_a_failed_request_is_swallowed, test_the_module_reads_no_preference); wrapper e2e on the fake web tests/characterization-69/test_the_launch_counter_is_one_plain_get_before_any_page_e2e.py::test_the_launch_counter_is_one_plain_get_before_any_page_e2e (the hook is reached at launch)

## What it does

An anonymous launch counter. Once per browser process, from the hook in
BrowserGlue._beforeUIStartup (the first statement, before SessionStartup.init
and before any page can exist), StealthLaunchCounter.fire() sends one GET with
no payload, credentials omitted and cache no-store to a fixed release asset
whose download count is the global launch counter. Errors are swallowed inside
fire() and by the try/catch of the hook line. The address is a constant of the module, the same in every binary. It
adds traffic of our own and removes nothing of Firefox's. The disclosure is in
the README of the tree (STEALTH_README.md, one pointer line in README.md).

## Hooks in Mozilla files

- `browser/components/BrowserGlue.sys.mjs`: in `BrowserGlue.prototype._beforeUIStartup`, one line as the first statement: `try { ChromeUtils.importESModule("resource:///modules/StealthLaunchCounter.sys.mjs").StealthLaunchCounter.fire(); } catch {}`. The try/catch keeps an error of the counter (even the import failing) from skipping `SessionStartup.init()`; the module is loaded at that statement, the same moment the lazy getter loaded it (the getter entry in Mozilla's `defineESModuleGetters` list is gone, the line imports the module itself).
- `browser/components/moz.build`: `EXTRA_JS_MODULES += ["StealthLaunchCounter.sys.mjs"]` after the closing `]` of the list.
- `browser/components/tests/unit/xpcshell.toml`: the entry of the test, the last line of the file after an empty line (a Mozilla addition after it would be a textual conflict; the other way is a second manifest).

## Our own files

- `browser/components/StealthLaunchCounter.sys.mjs`
- `browser/components/tests/unit/test_stealth_launch_counter.js`
