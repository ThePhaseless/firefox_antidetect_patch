/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_StealthLinuxSandboxBranding_h
#define mozilla_StealthLinuxSandboxBranding_h

// Included by SandboxBrokerPolicyFactory.cpp only, through the
// STEALTH-HOOK(fingerprint/js-surface/branding) include.

#include "mozilla/SandboxBroker.h"
#include "mozilla/net/StealthBranding.h"
#include "nsCOMPtr.h"
#include "nsIFile.h"
#include "nsString.h"

namespace mozilla {

/**
 * Gives the content processes READ access to exactly the declared branding
 * archive.
 *
 * The branding a page reads is declared by invisible_core, which keeps the
 * archive wherever it is installed. The content processes load from it, so they
 * get READ access to exactly that file - the same one the declaration gate
 * accepted, through the same function (StealthBrandingDeclaredArchive, see
 * netwerk/protocol/res/StealthBranding.h). It is one read-only rule on that
 * path (SandboxBroker::MAY_READ, the value of the `rdonly` constant of
 * SandboxBrokerPolicyFactory.cpp).
 *
 * Nothing is added, and nothing is said, when the engine is off or the
 * declaration is not usable (StealthBrandingDeclaredArchive returns null), or
 * when the archive's path cannot be read.
 *
 * Called from SandboxBrokerPolicyFactory::InitContentPolicy with the policy it
 * builds, right after the rules of security.sandbox.content.read_path_whitelist
 * and before the rule for userContent.css, so the order of the rules does not
 * change. (The Windows counterpart is the overload of this name in
 * security/sandbox/win/src/sandboxbroker/StealthSandboxBranding.h.)
 */
inline void StealthBrandingAddReadRule(SandboxBroker::Policy* aPolicy) {
  if (nsCOMPtr<nsIFile> branding =
          mozilla::net::StealthBrandingDeclaredArchive()) {
    nsAutoCString brandingPath;
    if (NS_SUCCEEDED(branding->GetNativePath(brandingPath))) {
      aPolicy->AddPath(SandboxBroker::MAY_READ, brandingPath.get());
    }
  }
}

}  // namespace mozilla

#endif  // mozilla_StealthLinuxSandboxBranding_h
