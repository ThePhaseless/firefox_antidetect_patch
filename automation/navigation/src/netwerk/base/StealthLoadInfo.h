/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_net_StealthLoadInfo_h
#define mozilla_net_StealthLoadInfo_h

#include "nscore.h"

namespace mozilla {

class OriginAttributes;

namespace net {

class LoadInfo;
class TRRLoadInfo;

// The copy of a LoadInfo (Clone, CloneWithNewSecFlags and CloneForNewRequest
// all go through LoadInfo's copy constructor) keeps the identifier of the load
// it belongs to (nsILoadInfo.jugglerLoadIdentifier), so a redirect's request
// is still the navigation's. Called as the one statement of the copy
// constructor's body: the member is the one that constructor leaves at its
// default, and nothing runs between the init list and the body.
void StealthLoadInfoCopied(LoadInfo* aThis, const LoadInfo& aRhs);

// TRRLoadInfo::SetOriginAttributes keeps what it is given (Mozilla's refuses),
// so a DNS-over-HTTPS request carries the context of the lookup that caused it
// and its proxy filter sees it. aField is TRRLoadInfo's member; *aRv is the
// result of the setter. Always true.
bool StealthTRRSetOriginAttributes(OriginAttributes& aField,
                                   const OriginAttributes& aValue,
                                   nsresult* aRv);

// TRRLoadInfo::Clone: the clone of a load info that carries a context carries
// it too (a redirect of the DoH request is made on a clone, and stays in the
// same context, so it leaves by the same proxy). aClone is the object Clone has
// just made, handed back for Clone to own; the attributes are given by the
// public getter of aFrom and the setter of aClone (the one above), which are
// the accessors of nsILoadInfo and not const, though the getter writes nothing.
TRRLoadInfo* StealthTRRCloneContext(const TRRLoadInfo* aFrom,
                                    TRRLoadInfo* aClone);

}  // namespace net
}  // namespace mozilla

#endif  // mozilla_net_StealthLoadInfo_h
