/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this file,
 * You can obtain one at http://mozilla.org/MPL/2.0/. */

// createPattern() from a canvas takes the snapshot a page reads: the element's own GetSurfaceSnapshot, where the noise of a
// WebGL or WebGPU canvas is applied (nsICanvasRenderingContextInternal::StealthGetSurfaceSnapshot, which asks
// CanvasUtils::StealthPageSnapshotOf). The snapshot of the context itself is never taken when the context has an element: it
// would read a WebGL canvas back for nothing. The control is the context that has none, for which the count of its own
// snapshot is 1, so the zeros above it say something.

#include "gtest/gtest.h"
#include "mozilla/RefPtr.h"
#include "mozilla/dom/StealthCanvasUtils.h"
#include "mozilla/gfx/2D.h"

namespace mozilla::dom {

namespace {

struct FakeElement {
  int mOwnSnapshots = 0;
  already_AddRefed<gfx::SourceSurface> GetSurfaceSnapshot() {
    ++mOwnSnapshots;
    return nullptr;
  }
};

}  // namespace

TEST(StealthCanvasPageSnapshot, TheSnapshotOfTheContextIsNotTakenWhenItHasAnElement)
{
  int contextSnapshots = 0;
  auto contextOwn = [&]() -> already_AddRefed<gfx::SourceSurface> {
    ++contextSnapshots;
    return nullptr;
  };
  FakeElement* const noElement = nullptr;

  // A canvas element's context.
  FakeElement canvas;
  RefPtr<gfx::SourceSurface> surface =
      CanvasUtils::StealthPageSnapshotOf(&canvas, noElement, contextOwn);
  EXPECT_EQ(canvas.mOwnSnapshots, 1);
  EXPECT_EQ(contextSnapshots, 0);

  // An OffscreenCanvas's context.
  FakeElement offscreen;
  surface = CanvasUtils::StealthPageSnapshotOf(noElement, &offscreen, contextOwn);
  EXPECT_EQ(offscreen.mOwnSnapshots, 1);
  EXPECT_EQ(contextSnapshots, 0);

  // The control: a context with no element answers with its own snapshot, once, and no element is asked.
  FakeElement none;
  surface = CanvasUtils::StealthPageSnapshotOf(noElement, noElement, contextOwn);
  EXPECT_EQ(contextSnapshots, 1);
  EXPECT_EQ(none.mOwnSnapshots, 0);
}

}  // namespace mozilla::dom
