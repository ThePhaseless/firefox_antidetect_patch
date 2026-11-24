# fingerprint/js-surface/debugger

Category: other, spoof
Prefs: zoom.stealth.debugger.force_detach (read in JS by ThreadActor.attach, default false, no entry in StaticPrefList.yaml)
Test: gtest:StealthDebugger.* (devtools/shared/heapsnapshot/tests/gtest/TestStealthDebugger.cpp: a Debugger with stealthMode leaves no debugger in the debuggee realm; attach, removal and collection; the control of each case is the same Debugger without stealthMode), node:juggler/tests/a_forced_detach_returns_before_the_thread_attaches.test.mjs (the guard of attach() runs before any statement of Mozilla's)

## What it does

A Debugger whose object has the property `stealthMode` set to true (Juggler sets it right after `new Debugger()`, juggler/content/Runtime.js, before any addDebuggee) tracks its debuggees (`debuggees`, `debuggeeZones`: steps 2 and 3 of `Debugger::addDebuggeeGlobal`) but does not register in `Realm::debuggers_` (step 1) and does not put the realm in debug mode (step 5). The realm reports no debuggers (`hasDebuggers()` false), Ion stays enabled and there is no slow native-call path: a page realm that Juggler debugs is indistinguishable from a never-debugged one. `executeInGlobal` and the teardown at GC use `debuggees`/`debuggeeZones`, not `debuggers_`, so Juggler keeps working.

`stealthMode` is a property of the Debugger object, not a pref. It is read before the no-GC region (the read can run JS) and cached in the plain field `Debugger::invisibleDebuggee_`, because `removeDebuggeeGlobal` can run during the GC sweep (a Debugger or its debuggee collected), where JS cannot run, and there it must not erase an entry that was never pushed (`findDebuggerInVector` asserts the entry exists; `erase` on `end()` is undefined). The field must stay a plain bool.

`zoom.stealth.debugger.force_detach`: with the pref true `ThreadActor.attach` returns at once and the thread actor never attaches through this path (the name says detach, the effect is the early return of `alreadyAttached`).

## Hooks in Mozilla files

Each is one line with the marker on the line.

- `devtools/server/actors/thread.js`: guard, the first statement of `ThreadActor.attach`: `if (Services.prefs.getBoolPref("zoom.stealth.debugger.force_detach", false)) return;`. The pref is read through `Services` (no devtools module of ours: the strict `Stealth<Cosa>` form would need a module, its `DevToolsModules` entry and a require, three hooks instead of one).
- `js/src/debugger/Debugger.cpp`:
  - the include of `debugger/StealthDebugger.h`, in a block of ours after Mozilla's includes;
  - anchor in `Debugger::addDebuggeeGlobal`, right after the block that wraps `debuggeeLink` and before `JS::AutoAssertNoGC nogc;`: `mozilla::StealthDebuggerReadMode(cx, object, &invisibleDebuggee_);`. The field is passed (G14: no friend). Why an anchor: the read has to happen in the debuggee's realm (after `AutoRealm ar(cx, global)`) and before the no-GC region, and a guard at the top would run in the debugger's realm and also on the early return for an already-added debuggee;
  - the two Mozilla statements of step (1) that a stealth debuggee skips are untouched Mozilla lines, with one line of ours each (anchors): an unbraced `if (!invisibleDebuggee_)` right after `auto& globalDebuggers = global->getDebuggers(nogc);`, in front of Mozilla's `if (!globalDebuggers.append(...)) {...}` (no entry is pushed in `Realm::debuggers_`; `globalDebuggers` is a local born on the line above and the member it reads is set in the middle of the function, so a guard at the head has neither); and `mozilla::StealthDebuggerReleaseIfInvisible(invisibleDebuggee_, globalDebuggersGuard);` right after Mozilla's `auto globalDebuggersGuard = MakeScopeExit([&] { globalDebuggers.popBack(); });` (a stealth debuggee releases the rollback guard as soon as it is made, so it never pops an entry that was not pushed; `release()` is idempotent). The same calls are skipped for a stealth debuggee and none for any other, and no Mozilla call is added;
  - the early return between steps (3) and (4), an anchor after the scope-exit guard `debuggeeZonesGuard`: `if (invisibleDebuggee_) return mozilla::StealthDebuggerReleaseGuards(globalDebuggersGuard, debuggeesGuard, debuggeeZonesGuard);` (releases the rollback guards, locals of Mozilla's function, and returns true: steps 4 and 5, the allocation-tracking builder and `Realm::setIsDebuggee`/`ensureExecutionObservabilityOfRealm`, are skipped);
  - declared exception (G35, approved by the pm), in `removeDebuggeeGlobal`: the prefix `if (!invisibleDebuggee_)` before Mozilla's two erase lines, which stay as they are, not re-indented (a stealth debuggee never kept an entry; `findDebuggerInVector` asserts the entry exists).
  For the port to 160: Mozilla changed `append(Realm::DebuggerVectorEntry(this, debuggeeLink))` into `emplaceBack(this, debuggeeLink)`; the line stays Mozilla's, so the port takes 160's line behind the unbraced prefix. Nothing else differs between 159 and 160 in `addDebuggeeGlobal`/`removeDebuggeeGlobal`.
- `js/src/debugger/Debugger.h`: member `bool invisibleDebuggee_ = false;` between `allocationsLog` and `trackingAllocationSites`.
- `devtools/shared/heapsnapshot/tests/gtest/moz.build`: `UNIFIED_SOURCES += ["TestStealthDebugger.cpp"]` after the `FINAL_LIBRARY` line (registration of our gtest in the existing heapsnapshot gtest library).

## Our own files

- `js/src/debugger/StealthDebugger.h`: all in namespace `mozilla`: `StealthDebuggerReadMode(cx, debuggerObject)` (reads `stealthMode`; failure of the read means not stealth) and its overload with the field `bool*` that the anchor calls; `StealthDebuggerReleaseIfInvisible(invisible, guard)` (releases the guard when the debuggee is stealth); `StealthDebuggerReleaseGuards(guards...)` (releases the guards, returns true).
- `devtools/shared/heapsnapshot/tests/gtest/TestStealthDebugger.cpp`: suite `StealthDebugger`. The observable is the cycle check of `addDebuggeeGlobal`: a Debugger living in the debuggee realm that tries to debug the debugger's global finds a cycle only if the debuggee realm has debuggers. Cases: attach, removal and collection of the Debugger (the sweep calls `removeDebuggeeGlobal`), each in stealth mode and as a control without it.
- `juggler/tests/a_forced_detach_returns_before_the_thread_attaches.test.mjs`: runs the `attach()` method of thread.js with a recording `this` and a stub of `Services.prefs`; control with the pref false.
