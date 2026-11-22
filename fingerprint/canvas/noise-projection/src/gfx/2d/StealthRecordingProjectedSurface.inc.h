/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// Included by gfx/2d/DrawTargetRecording.cpp, in position: right after the
// definition of SourceSurfaceRecording, a class local to that .cpp that
// StealthProjectedStandIn (StealthCanvasProjection.h) has to see, so the
// definition cannot live in a file of its own. Not a header: it defines a
// member of DrawTargetRecording and is included once.

already_AddRefed<SourceSurface> DrawTargetRecording::StealthProjectedSurface(
    SourceSurface* aSurface, bool aPremultiplied,
    const StealthCanvasNoise& aNoise) {
  return StealthProjectedStandIn<SourceSurfaceRecording>(
      this, mRecorder.get(), aSurface, aPremultiplied, aNoise);
}
