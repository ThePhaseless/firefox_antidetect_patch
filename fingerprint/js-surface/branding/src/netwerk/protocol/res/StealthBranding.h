/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_net_StealthBranding_h
#define mozilla_net_StealthBranding_h

#include "mozilla/AlreadyAddRefed.h"
#include "nsError.h"
#include "nsStringFwd.h"

class nsIFile;
class nsIURI;

namespace mozilla::net {

/**
 * The branding a page can read is DECLARED by invisible_core, files and all.
 *
 * A page reaches the branding package's content directory two ways:
 * chrome://branding/content/ (the package is contentaccessible) and
 * resource://usercontext-content/branding/ (that host maps the whole of
 * browser/content/, contentaccessible too). What it reads there - the about
 * dialog's stylesheet rules, the wordmarks' boxes, the images' sizes - tells a
 * build from the retail one. By engine rule 7 what a page reads lives in
 * invisible_core and nowhere else, so the core ships the files (the retail
 * brand, ours, or an archive of the caller's own) and declares where they
 * are, `zoom.stealth.branding.archive`, a file: URI of a zip archive whose
 * entries are the files. The engine keeps no stealth copy of any of them and
 * serves the declared ones, as jar: - the channel class the retail serves its
 * branding with out of omni.ja, so a page sees the same channel behaviour (a
 * file: channel keeps a loader's content-type hint, a jar: one does not).
 *
 * Both ways end in the same place: a URI under the branding package's content
 * directory. So the redirect is one function called at the two places that
 * resolve those URIs - nsChromeRegistry::ConvertChromeURL and
 * SubstitutingProtocolHandler::ResolveURI - instead of one rule per scheme that
 * could drift apart. A page comparing the two ways gets the same files by
 * construction.
 *
 * Engine off (no seed) is stock Firefox and serves the build's own brand: that
 * is the absence of a declaration, not an incomplete one. Engine on and nothing
 * or something malformed declared refuses: the parent's declaration gate stops
 * the launch, and a load that still gets here fails rather than serving the
 * build's own brand, which would be the compiled fallback rule 7 forbids.
 */

/**
 * Called by the chrome registry, in the parent and in every content process,
 * whenever a package's content directory is registered
 * (nsChromeRegistryChrome::ManifestContent after it records the package,
 * nsChromeRegistryContent::RegisterPackage after it resolves the directory).
 * Only the branding package is kept: where the branding directory is, for the
 * declared-branding redirect. A registry reset re-registers every package, so
 * the last registration wins and nothing needs clearing. The content process
 * resolves branding URIs itself, so it needs to know where the branding
 * directory is too: it calls this for every package with a content directory,
 * and a package that has none in this process (aBase null) is ignored.
 */
void StealthBrandingRegisterPackage(const nsACString& aPackage, nsIURI* aBase);

/**
 * The content directory the registries last recorded for the branding package
 * (ends with '/'), for the tests: false when none has been recorded in this
 * process.
 */
bool StealthBrandingRecordedDirectory(nsACString& aDirectory);

/**
 * Rewrites a resolved URI spec that points into the branding package's content
 * directory so that it points into the declared archive instead (jar:<archive>!/).
 * Leaves every
 * other spec untouched. Returns NS_ERROR_FILE_NOT_FOUND - a failed load, never
 * the build's own brand - when the engine is on and the declaration is missing
 * or malformed. Safe on any thread: ResolveURI is called off the main thread
 * too.
 *
 * SubstitutingProtocolHandler::ResolveURI (defined in StealthBranding.cpp, around
 * Mozilla's ResolveURI_Mozilla) calls it on every successful resolution, the
 * special cases included, so the declared branding applies on every way a URI
 * can reach the branding directory, and resource://usercontext-content/branding/
 * reads the same declared set as chrome://branding/content/. A failed
 * resolution is returned as it is, not redirected.
 */
nsresult StealthBrandingRedirect(nsACString& aResolvedSpec);

/**
 * Wraps the URI nsChromeRegistry::ConvertChromeURL resolves in its last step
 * (aRv is the result of NS_NewURI(aResult, path, nullptr, baseURI), which has
 * written *aResult). Runs the resolved spec through StealthBrandingRedirect so
 * that chrome://branding/content/ reads the set invisible_core declares,
 * through the same function as resource://usercontext-content/branding/. The
 * two ways a page reaches the branding cannot disagree. When the redirect leaves
 * the spec unchanged (engine off, or not a branding URI) the URI resolved by the
 * stock call is returned as is, with no second parse. Otherwise a new URI is
 * built from the declared spec and the resolved one is released. A failed aRv,
 * or a failure of GetSpec or of the redirect, is returned with *aResult empty,
 * as when the registry itself fails. Runs on the thread of its caller.
 */
nsresult StealthBrandingChromeURL(nsresult aRv, nsIURI** aResult);

/**
 * Whether a declaration is well formed: a file: URI of a file, i.e. starting
 * with "file:///", not ending with '/', without a backslash or a '!' (which
 * would end the archive part of the jar: URI). The redirect checks only this,
 * on any thread; everything else is checked once, in the parent, through
 * StealthBrandingDeclaredArchive.
 */
bool StealthBrandingIsDeclaredArchive(const nsACString& aSpec);

/**
 * The declared archive, or null when the engine is off or the declaration is
 * not usable: malformed, not an existing regular file, not a zip, empty, or
 * holding anything but files at its root. Parent process. Two readers, and they
 * must agree, which is why it is one function: the declaration gate refuses the
 * launch when it is null, and the content sandbox grants READ access to exactly
 * this file - it lives wherever invisible_core keeps it, which the sandbox would
 * otherwise keep closed to the content processes that load from it.
 * SandboxBrokerPolicyFactory::InitContentPolicy (Linux) adds this file as a
 * READ rule for the content processes: the branding a page reads is declared
 * by invisible_core, which keeps the archive wherever it is installed; the
 * content processes load from it, so they get READ access to exactly that file
 * - the same one the declaration gate accepted, through the same function.
 */
already_AddRefed<nsIFile> StealthBrandingDeclaredArchive();

}  // namespace mozilla::net

#endif  // mozilla_net_StealthBranding_h
