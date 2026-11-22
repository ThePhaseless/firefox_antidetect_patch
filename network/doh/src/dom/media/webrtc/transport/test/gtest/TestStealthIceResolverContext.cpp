/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// STEALTH-HOOK(network/doh)
//
// The name of an ICE server is looked up in the browser context of the page that made
// the PeerConnection: NrIceResolver gives the DNS service the attributes it holds
// (through StealthIceResolverLookupAttributes), and MediaTransportImplNicer::SetProxyConfig
// fills them from the load info of the PeerConnection's proxy config through
// StealthIceResolverSetContext and StealthIceResolverAttributes.
// Red on the old code: the resolver had no attributes (every lookup used the default
// ones) and the function does not exist.
//
// The lookup itself (AsyncResolveNative on the STS thread) needs the DNS service and a
// live ICE context; the gtests cover what decides its attributes. The call into the
// DNS service is one line of source, guarded in
// juggler/tests/the_ice_name_is_resolved_in_the_context_of_the_peer_connection.test.mjs.

#include "gtest/gtest.h"

#include "mozilla/OriginAttributes.h"
#include "mozilla/RefPtr.h"
#include "nsString.h"
#include "nriceresolver.h"

using namespace mozilla;

namespace {

OriginAttributes ContextWithUser(uint32_t aUserContextId) {
  OriginAttributes attrs;
  attrs.mUserContextId = aUserContextId;
  return attrs;
}

}  // namespace

TEST(StealthIceResolverContext, TheDefaultContextStaysTheDefaultAttributes) {
  OriginAttributes attrs =
      StealthIceResolverAttributes(OriginAttributes());
  EXPECT_EQ(0u, attrs.mUserContextId);
  nsAutoCString suffix;
  attrs.CreateSuffix(suffix);
  EXPECT_TRUE(suffix.IsEmpty());
}

TEST(StealthIceResolverContext, TheUserContextOfThePeerConnectionIsKept) {
  OriginAttributes attrs = StealthIceResolverAttributes(ContextWithUser(6));
  EXPECT_EQ(6u, attrs.mUserContextId);
  nsAutoCString suffix;
  attrs.CreateSuffix(suffix);
  EXPECT_EQ("^userContextId=6"_ns, suffix);
}

TEST(StealthIceResolverContext, OnlyTheUserContextIsKept) {
  OriginAttributes pc = ContextWithUser(6);
  pc.mFirstPartyDomain.AssignLiteral("example.test");
  pc.mPrivateBrowsingId = 1;
  OriginAttributes attrs = StealthIceResolverAttributes(pc);
  EXPECT_EQ(6u, attrs.mUserContextId);
  EXPECT_TRUE(attrs.mFirstPartyDomain.IsEmpty());
  EXPECT_EQ(0u, attrs.mPrivateBrowsingId);
}

TEST(StealthIceResolverContext, TheResolverStartsWithTheDefaultAttributes) {
  // No SetProxyConfig (no BrowserChild, Android): as upstream.
  RefPtr<NrIceResolver> resolver = MakeRefPtr<NrIceResolver>();
  EXPECT_EQ(0u, resolver->GetOriginAttributes().mUserContextId);
  nsAutoCString suffix;
  resolver->GetOriginAttributes().CreateSuffix(suffix);
  EXPECT_TRUE(suffix.IsEmpty());
}

TEST(StealthIceResolverContext, TheResolverPassesTheContextItWasGiven) {
  RefPtr<NrIceResolver> resolver = MakeRefPtr<NrIceResolver>();
  resolver->SetOriginAttributes(StealthIceResolverAttributes(ContextWithUser(6)));
  EXPECT_EQ(6u, resolver->GetOriginAttributes().mUserContextId);
  // Another PeerConnection's resolver is its own.
  RefPtr<NrIceResolver> other = MakeRefPtr<NrIceResolver>();
  EXPECT_EQ(0u, other->GetOriginAttributes().mUserContextId);
}

// MediaTransportImplNicer::SetProxyConfig hands its resolver and the proxy config to StealthIceResolverSetContext, which gives
// the resolver the context of the PeerConnection and nothing else of its attributes. No resolver (the transport is shut down):
// nothing to do. Red on the old code: the function does not exist, and the resolver had no attributes of its own.
TEST(StealthIceResolverContext, TheResolverOfAPeerConnectionIsGivenItsContext) {
  RefPtr<NrIceResolver> resolver = MakeRefPtr<NrIceResolver>();
  StealthIceResolverSetContext(resolver, ContextWithUser(6));
  EXPECT_EQ(6u, resolver->GetOriginAttributes().mUserContextId);

  OriginAttributes pc = ContextWithUser(7);
  pc.mFirstPartyDomain.AssignLiteral("example.test");
  pc.mPrivateBrowsingId = 1;
  RefPtr<NrIceResolver> other = MakeRefPtr<NrIceResolver>();
  StealthIceResolverSetContext(other, pc);
  EXPECT_EQ(7u, other->GetOriginAttributes().mUserContextId);
  EXPECT_TRUE(other->GetOriginAttributes().mFirstPartyDomain.IsEmpty());
  EXPECT_EQ(0u, other->GetOriginAttributes().mPrivateBrowsingId);

  RefPtr<NrIceResolver> none;
  StealthIceResolverSetContext(none, ContextWithUser(6));
  EXPECT_EQ(nullptr, none.get());
}

// NrIceResolver::resolve passes the attributes of its lookup through StealthIceResolverLookupAttributes: those the resolver was
// given, or the ones Mozilla's code made while it has none.
TEST(StealthIceResolverContext, TheLookupOfAnIceServerNameCarriesTheAttributesOfItsResolver) {
  RefPtr<NrIceResolver> resolver = MakeRefPtr<NrIceResolver>();
  OriginAttributes upstream;
  upstream.mPrivateBrowsingId = 1;
  OriginAttributes attrs;
  StealthIceResolverLookupAttributes(resolver, &attrs);
  EXPECT_TRUE(attrs == OriginAttributes());
  resolver->SetOriginAttributes(StealthIceResolverAttributes(ContextWithUser(6)));
  StealthIceResolverLookupAttributes(resolver, &attrs);
  EXPECT_EQ(6u, attrs.mUserContextId);
  OriginAttributes kept = upstream;
  StealthIceResolverLookupAttributes(nullptr, &kept);
  EXPECT_TRUE(kept == upstream);
}
