/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The Selenium atoms Firefox ships with the remote agent (remote/marionette/atom.sys.mjs), as source text, for
// PageAgent._elementAtom, which runs them through Xrays in its own sandbox. Mozilla's module keeps its table (ATOMS) to
// itself; the last line of the module hands it to stealthRegisterAtoms when the module is evaluated, and
// stealthAtomSources gives it back, the same object, after making sure the module has been evaluated.

let sources = null;

export function stealthRegisterAtoms(aSources) {
  sources = aSources;
}

export function stealthAtomSources() {
  ChromeUtils.importESModule(
    "chrome://remote/content/marionette/atom.sys.mjs"
  );
  return sources;
}
