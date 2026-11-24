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
that it does not export. The module's only change is that export.

## Hooks in Mozilla files

- `remote/marionette/atom.sys.mjs` (registration, module level, right after the closing `};` of `const ATOMS = {...}`): `export const ATOM_SOURCES = ATOMS;`. One added line, the same export as before; the three comment lines that were above it left the file (the reason is here and in the comment of `Page._elementAtom` in `juggler/content/PageAgent.js`, the only consumer: `ATOM_SOURCES[atom]` run with `Cu.evalInSandbox`). It breaks, loudly, if Mozilla renames `ATOMS`: the module then fails to load.
- Alternative rejected: Juggler extracting the object from the text of the module. It is brittle if Mozilla regenerates the atoms.

## Our own files

None: the logic is in juggler/content/PageAgent.js (folder automation/juggler).
