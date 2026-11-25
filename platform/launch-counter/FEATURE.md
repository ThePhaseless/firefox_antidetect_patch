# platform/launch-counter

Category: other
Prefs: none (the counter is mandatory: no preference gates it and none moves it)
Test: browser/components/tests/unit/test_stealth_launch_counter.js (xpcshell: test_sends_one_plain_get_to_the_fixed_address, test_old_prefs_neither_stop_it_nor_move_it, test_a_failed_request_is_swallowed, test_the_module_reads_no_preference); wrapper e2e on the fake web tests/characterization-69/test_the_launch_counter_is_one_plain_get_before_any_page_e2e.py::test_the_launch_counter_is_one_plain_get_before_any_page_e2e (the hook is reached at launch)

## What it does

An anonymous launch counter. Once per browser process, from the hook in
BrowserGlue._beforeUIStartup (the first statement, before SessionStartup.init
and before any page can exist), StealthLaunchCounterLoader.fire() imports the counter module and calls
StealthLaunchCounter.fire(), which sends one GET with
no payload, credentials omitted and cache no-store to a fixed release asset
whose download count is the global launch counter. Errors are swallowed inside
StealthLaunchCounter.fire() (a throw of fetch and a rejection of its promise), and the loader
stops any other failure (the counter module does not load, its fire() throws) and logs it once with
console.error, as the other modules of ours log what must not be missed, so a defect of the counter cannot
abort _beforeUIStartup. The address is a constant of the module, the same in every binary. It
adds traffic of our own and removes nothing of Firefox's. The disclosure is in
the README of the tree (STEALTH_README.md, one pointer line in README.md).

## Hooks in Mozilla files

- `browser/components/BrowserGlue.sys.mjs`: in `BrowserGlue.prototype._beforeUIStartup`, one plain call as the first statement: `ChromeUtils.importESModule("resource:///modules/StealthLaunchCounterLoader.sys.mjs").StealthLaunchCounterLoader.fire();`. The loader imports nothing at its top; the guarded import of the counter module is inside its `fire()`, so an error of the counter (even the import failing) stops there and `SessionStartup.init()` runs after the hook line as in Mozilla's file. The line imports the loader itself (there is no getter entry in Mozilla's `defineESModuleGetters` list).
- `browser/components/moz.build`: `EXTRA_JS_MODULES += ["StealthLaunchCounter.sys.mjs", "StealthLaunchCounterLoader.sys.mjs"]` after the closing `]` of the list.
- `browser/components/tests/unit/xpcshell.toml`: the entry of the test, the last line of the file after an empty line (a Mozilla addition after it would be a textual conflict; the other way is a second manifest).

## Our own files

- `browser/components/StealthLaunchCounter.sys.mjs`
- `browser/components/StealthLaunchCounterLoader.sys.mjs`
- `browser/components/tests/unit/test_stealth_launch_counter.js`
