# automation/element-atoms

Category: juggler
Prefs: none read directly
Test: the wrapper's e2e tests/test_page_element_atoms_run_in_a_sandbox_e2e.py (visible and hidden element, is_visible and inner_text; red when the export is missing); the measurement noted in Page._elementAtom (juggler/content/PageAgent.js): 24 elements with both atoms, 48 answers of 48 equal to Marionette's run in the same engine

## What it does

Juggler's `Page.elementAtom` answers `getVisibleText` and `isElementDisplayed` for an
element with the Selenium atoms that Firefox ships with the remote agent
(`remote/marionette/atom.sys.mjs`). Marionette runs the atoms in a sandbox with the
Xrays waived, so a page that replaced `getComputedStyle` or `getBoundingClientRect`
sees every call. Juggler runs the same sources in a sandbox of its own, through
Xrays: the page's own functions are never called and the answer is Marionette's.
For that it needs the table of sources, which Mozilla's module keeps in a constant
that it does not export. The module's only change is its last line, which hands the
table (`ATOMS`) to a module of ours.

## Hooks in Mozilla files

- `remote/marionette/atom.sys.mjs` (anchor, the last line of the module, G33): `ChromeUtils.importESModule("resource://gre/modules/juggler/StealthAtoms.sys.mjs").stealthRegisterAtoms(ATOMS);`. One added line; `ATOMS` is the module's own constant and is read after its declaration, and nothing of Mozilla's is changed. It breaks, loudly, if Mozilla renames `ATOMS`: the module then fails to load.
- `juggler/moz.build`: `"StealthAtoms.sys.mjs"` in the list of modules packaged under `modules/juggler`.
- Alternative rejected: Juggler extracting the object from the text of the module. It is brittle if Mozilla regenerates the atoms.

## Our own files

- `juggler/StealthAtoms.sys.mjs`: `stealthRegisterAtoms(table)` keeps the table that Marionette's module hands over, and `stealthAtomSources()` gives back the same object after making sure Marionette's module has been evaluated. Same table, same sandbox, same run.
- `juggler/tests/element_atoms_reach_juggler_by_the_last_line_of_their_module.test.mjs`: a run of the module with a stand-in for `ChromeUtils`, a negative control, and the guards of the two lines.
- The consumer is `juggler/content/PageAgent.js` (folder automation/juggler): `Page._elementAtom` asks `stealthAtomSources()`.
