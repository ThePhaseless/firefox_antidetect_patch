/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The time and the language a page reads are the declared ones, never the
// host's (fingerprint/locale-time/timezone). The hooks in Mozilla's files call
// the functions below; these tests pin what each answers.

#include "gtest/gtest.h"
#include "mozilla/BasePrincipal.h"
#include "mozilla/OriginAttributes.h"
#include "mozilla/Preferences.h"
#include "mozilla/dom/Document.h"
#include "mozilla/dom/StealthSessionDeclaration.h"
#include "nsCOMPtr.h"
#include "nsIURI.h"
#include "nsNetUtil.h"
#include "nsString.h"
#include "prtime.h"

// In the namespace itself, not by using-directives: this file shares a unified
// translation unit with others that have their own.
namespace mozilla::dom {

namespace {

// 2026-10-21 07:28:00 UTC, the instant of `Last-Modified: Wed, 21 Oct 2026
// 07:28:00 GMT`. Chatham (UTC+13:45 with daylight saving then) reads 21:13 and
// Kolkata (UTC+05:30) 12:58 on the same day.
constexpr PRTime kInstant = PRTime(1792567680) * PR_USEC_PER_SEC;

// A document with no context and no window: the zone it asks for is the
// session's.
already_AddRefed<Document> CreateDoc() {
  nsCOMPtr<nsIURI> uri;
  NS_NewURI(getter_AddRefs(uri), "data:text/html,");
  RefPtr<BasePrincipal> principal =
      BasePrincipal::CreateContentPrincipal(uri, OriginAttributes());
  MOZ_RELEASE_ASSERT(principal);
  nsCOMPtr<Document> doc;
  MOZ_ALWAYS_SUCCEEDS(NS_NewDOMDocument(getter_AddRefs(doc), u""_ns, u""_ns,
                                        nullptr, uri, uri, principal,
                                        LoadedAsData::No, nullptr,
                                        DocumentFlavor::HTML));
  MOZ_RELEASE_ASSERT(doc);
  return doc.forget();
}

// The session's declaration, as the core writes it, for the life of a test.
struct DeclaredZone {
  explicit DeclaredZone(const char* aZone) {
    Preferences::SetCString("juggler.timezone.override", aZone);
  }
  ~DeclaredZone() { Preferences::ClearUser("juggler.timezone.override"); }
};

struct DeclaredLanguageList {
  explicit DeclaredLanguageList(const char* aList) {
    Preferences::SetCString("juggler.locale.override", aList);
  }
  ~DeclaredLanguageList() {
    Preferences::ClearUser("juggler.locale.override");
  }
};

}  // namespace

// StealthExplodeTime: PR_LocalTimeParameters is the page's local time.

TEST(StealthTimezone, LocalTimeIsTheDeclaredZonesWallClock)
{
  RefPtr<Document> doc = CreateDoc();
  PRExplodedTime chatham;
  {
    DeclaredZone zone("Pacific/Chatham");
    StealthExplodeTime(doc, kInstant, PR_LocalTimeParameters, &chatham);
  }
  EXPECT_EQ(chatham.tm_year, 2026);
  EXPECT_EQ(chatham.tm_month, 9);  // October, zero-based
  EXPECT_EQ(chatham.tm_mday, 21);
  EXPECT_EQ(chatham.tm_hour, 21);
  EXPECT_EQ(chatham.tm_min, 13);
  EXPECT_EQ(chatham.tm_sec, 0);
  // Standard time 12:45 plus one hour of daylight saving: EXSLT prints the sum.
  EXPECT_EQ(chatham.tm_params.tp_gmt_offset, 12 * 3600 + 45 * 60);
  EXPECT_EQ(chatham.tm_params.tp_dst_offset, 3600);

  PRExplodedTime kolkata;
  {
    DeclaredZone zone("Asia/Kolkata");
    StealthExplodeTime(doc, kInstant, PR_LocalTimeParameters, &kolkata);
  }
  EXPECT_EQ(kolkata.tm_hour, 12);
  EXPECT_EQ(kolkata.tm_min, 58);
  EXPECT_EQ(kolkata.tm_params.tp_gmt_offset, 5 * 3600 + 30 * 60);
  EXPECT_EQ(kolkata.tm_params.tp_dst_offset, 0);
}

// The form the hooks of Document.cpp use: an anchor notes the document, the call
// that replaces Mozilla's PR_ExplodeTime has Mozilla's arguments and takes it.

TEST(StealthTimezone, TheNotedDocumentIsForTheNextCallOnly)
{
  RefPtr<Document> doc = CreateDoc();
  DeclaredZone zone("Pacific/Chatham");
  PRExplodedTime first, second, host;
  StealthNoteTimeDocument(doc);
  StealthExplodeTime(kInstant, PR_LocalTimeParameters, &first);
  // The second call has noted nothing: it is Mozilla's, not the first's.
  StealthExplodeTime(kInstant, PR_LocalTimeParameters, &second);
  PR_ExplodeTime(kInstant, PR_LocalTimeParameters, &host);
  EXPECT_EQ(first.tm_hour, 21);
  EXPECT_EQ(first.tm_min, 13);
  EXPECT_EQ(second.tm_hour, host.tm_hour);
  EXPECT_EQ(second.tm_min, host.tm_min);
  EXPECT_EQ(second.tm_params.tp_gmt_offset, host.tm_params.tp_gmt_offset);
}

TEST(StealthTimezone, NothingNotedIsMozillasPRExplodeTime)
{
  // Control: a zone is declared and no document is noted.
  DeclaredZone zone("Asia/Kolkata");
  PRExplodedTime ours, host;
  StealthExplodeTime(kInstant, PR_LocalTimeParameters, &ours);
  PR_ExplodeTime(kInstant, PR_LocalTimeParameters, &host);
  EXPECT_EQ(ours.tm_hour, host.tm_hour);
  EXPECT_EQ(ours.tm_min, host.tm_min);
  PRExplodedTime gmtOurs, gmtHost;
  StealthExplodeTime(kInstant, PR_GMTParameters, &gmtOurs);
  PR_ExplodeTime(kInstant, PR_GMTParameters, &gmtHost);
  EXPECT_EQ(gmtOurs.tm_hour, gmtHost.tm_hour);
}

TEST(StealthTimezone, TwoNotedDocumentsWithOppositeZonesDoNotLeak)
{
  RefPtr<Document> doc = CreateDoc();
  PRExplodedTime chatham, kolkata;
  {
    DeclaredZone zone("Pacific/Chatham");
    StealthNoteTimeDocument(doc);
    StealthExplodeTime(kInstant, PR_LocalTimeParameters, &chatham);
  }
  {
    DeclaredZone zone("Asia/Kolkata");
    StealthNoteTimeDocument(doc);
    StealthExplodeTime(kInstant, PR_LocalTimeParameters, &kolkata);
  }
  EXPECT_EQ(chatham.tm_hour, 21);
  EXPECT_EQ(kolkata.tm_hour, 12);
  EXPECT_EQ(kolkata.tm_min, 58);
}

// resistFingerprinting asks for UTC by passing PR_GMTParameters: the declared
// zone is not consulted.

TEST(StealthTimezone, GMTParametersAreUTCWhateverIsDeclared)
{
  RefPtr<Document> doc = CreateDoc();
  PRExplodedTime utc;
  {
    DeclaredZone zone("Pacific/Chatham");
    StealthExplodeTime(doc, kInstant, PR_GMTParameters, &utc);
  }
  EXPECT_EQ(utc.tm_hour, 7);
  EXPECT_EQ(utc.tm_min, 28);
  EXPECT_EQ(utc.tm_params.tp_gmt_offset, 0);
  EXPECT_EQ(utc.tm_params.tp_dst_offset, 0);
}

// Nothing declared (the engine launched without the core): Mozilla's own path,
// the C runtime's local time.

TEST(StealthTimezone, NothingDeclaredIsTheLocalTimeOfMozilla)
{
  RefPtr<Document> doc = CreateDoc();
  PRExplodedTime ours;
  PRExplodedTime host;
  StealthExplodeTime(doc, kInstant, PR_LocalTimeParameters, &ours);
  PR_ExplodeTime(kInstant, PR_LocalTimeParameters, &host);
  EXPECT_EQ(ours.tm_hour, host.tm_hour);
  EXPECT_EQ(ours.tm_min, host.tm_min);
  EXPECT_EQ(ours.tm_mday, host.tm_mday);
  EXPECT_EQ(ours.tm_params.tp_gmt_offset, host.tm_params.tp_gmt_offset);
  EXPECT_EQ(ours.tm_params.tp_dst_offset, host.tm_params.tp_dst_offset);
}

// BrowsingContext::DidSet reads the value of the field, or the session's when
// the field is empty.

TEST(StealthTimezone, AFieldWinsAndAnEmptyOneFallsToTheSession)
{
  DeclaredZone session("Asia/Kolkata");
  EXPECT_TRUE(StealthTimezoneOrSession(u"Pacific/Chatham"_ns)
                  .EqualsLiteral("Pacific/Chatham"));
  EXPECT_TRUE(StealthTimezoneOrSession(u""_ns).EqualsLiteral("Asia/Kolkata"));
  DeclaredLanguageList language("ja-JP, ja");
  EXPECT_TRUE(StealthLanguageOrSession("de-DE"_ns).EqualsLiteral("de-DE"));
  EXPECT_TRUE(StealthLanguageOrSession(""_ns).EqualsLiteral("ja-JP, ja"));
}

TEST(StealthTimezone, NothingDeclaredAndAnEmptyFieldIsEmpty)
{
  EXPECT_TRUE(StealthTimezoneOrSession(u""_ns).IsEmpty());
  EXPECT_TRUE(StealthLanguageOrSession(""_ns).IsEmpty());
}

}  // namespace mozilla::dom
