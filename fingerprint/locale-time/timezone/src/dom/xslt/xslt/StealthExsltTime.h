/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef mozilla_dom_StealthExsltTime_h
#define mozilla_dom_StealthExsltTime_h

#include "mozilla/Assertions.h"
#include "mozilla/dom/Document.h"
#include "mozilla/dom/StealthSessionDeclaration.h"
#include "prtime.h"
#include "txExecutionState.h"
#include "txIXPathContext.h"
#include "txXPathTreeWalker.h"

namespace mozilla::dom {

/**
 * EXSLT's date:date-time() (txEXSLTFunctions.cpp, DATE_TIME) explodes the time
 * in the zone the page declares: StealthExplodeTime of the document the stylesheet
 * is transforming. The document is found from the evaluation context the way
 * txEXSLTFunctions.cpp's getSourceDocument finds it, which is the same
 * document the function already reached for Mozilla's own calls (the source
 * document of the transformation's txExecutionState, also when the stylesheet
 * was reached through another one): the hook passes aContext, a parameter, not
 * the local that holds it. Mozilla's case has already refused a context with no
 * execution state or no document (NS_ENSURE_STATE(sourceDoc)); if that ever
 * changed, the time is exploded as Mozilla's own call does.
 */
inline void StealthExplodeTime(txIEvalContext* aContext, PRTime aTime,
                               PRTimeParamFn aParams,
                               PRExplodedTime* aExploded) {
  txExecutionState* es =
      static_cast<txExecutionState*>(aContext->getPrivateContext());
  Document* sourceDoc =
      es ? txXPathNativeNode::getDocument(es->getSourceDocument()) : nullptr;
  if (!sourceDoc) {
    PR_ExplodeTime(aTime, aParams, aExploded);
    return;
  }
  StealthExplodeTime(sourceDoc, aTime, aParams, aExploded);
}

}  // namespace mozilla::dom

#endif  // mozilla_dom_StealthExsltTime_h
