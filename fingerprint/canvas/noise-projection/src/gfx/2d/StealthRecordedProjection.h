/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef MOZILLA_GFX_STEALTHRECORDEDPROJECTION_H_
#define MOZILLA_GFX_STEALTHRECORDEDPROJECTION_H_

// The recorded event that carries the canvas noise projection
// (gfx/2d/StealthCanvasProjection.h) to the process that replays a canvas
// recording. Included by gfx/2d/RecordedEventImpl.h, which expands the event
// into its FOR_EACH_EVENT list (defined at the end of this file).
//
// Its type, STEALTHPROJECTSURFACE, is an enumerator without a value of its own
// in RecordedEvent::EventType, placed right before LAST (G3): the compiler
// numbers it. Recorded events travel only between processes of the same build
// (content to GPU process), never to disk or between versions, so the number
// is not part of any contract; the canvas events numbered from LAST on follow
// it, and CanvasTranslator::ReadPendingEvent bounds events by
// LAST_CANVAS_EVENT_TYPE, which moves with LAST.

#include <stdint.h>

#include <sstream>
#include <string>

#include "2D.h"
#include "RecordedEvent.h"
#include "RecordingTypes.h"
#include "mozilla/Attributes.h"
#include "mozilla/RefPtr.h"
#include "mozilla/gfx/StealthCanvasProjection.h"

namespace mozilla {
namespace gfx {

// The canvas noise applied where the pixels live: a canvas drawn onto a
// canvas that records for the GPU process is projected THERE
// (gfx::StealthProjectedRegion, which applies gfx::StealthProjectPixels to the
// source's stored pixels), so the drawing carries the same image every reader
// of the source reads, without bringing the source back to the content
// process. The seed travels with the event: the content process decides it
// (CanvasUtils::StealthNoise, with the canvas's principal), and the GPU
// process does not read the pref.
class RecordedStealthProjectSurface
    : public RecordedEventDerived<RecordedStealthProjectSurface> {
 public:
  RecordedStealthProjectSurface(ReferencePtr aSurface,
                                ReferencePtr aProjectedSurface,
                                bool aPremultiplied,
                                const StealthCanvasNoise& aNoise)
      : RecordedEventDerived(STEALTHPROJECTSURFACE),
        mSurface(aSurface),
        mProjectedSurface(aProjectedSurface),
        mPremultiplied(aPremultiplied),
        mSeed(aNoise.mSeed),
        mEdgeTolerance(aNoise.mEdgeTolerance) {}

  bool PlayEvent(Translator* aTranslator) const override;

  template <class S>
  void Record(S& aStream) const;
  void OutputSimpleEventInfo(std::stringstream& aStringStream) const override;

  std::string GetName() const override { return "StealthProjectSurface"; }

 private:
  friend class RecordedEvent;

  ReferencePtr mSurface;
  ReferencePtr mProjectedSurface;
  bool mPremultiplied = true;
  int32_t mSeed = 0;
  int32_t mEdgeTolerance = 0;

  template <class S>
  MOZ_IMPLICIT RecordedStealthProjectSurface(S& aStream);
};

inline bool RecordedStealthProjectSurface::PlayEvent(
    Translator* aTranslator) const {
  SourceSurface* surface = aTranslator->LookupSourceSurface(mSurface);
  if (!surface) {
    return false;
  }
  // No road back to the raw pixels: a source that cannot be read here fails
  // the event like any other unresolvable surface, it is not drawn unprojected.
  RefPtr<DataSourceSurface> data = surface->GetDataSurface();
  if (!data) {
    return false;
  }
  RefPtr<SourceSurface> projected = StealthProjectedRegion(
      data, IntRect(IntPoint(), data->GetSize()), mPremultiplied,
      StealthCanvasNoise{mSeed, mEdgeTolerance});
  if (!projected) {
    return false;
  }
  aTranslator->AddSourceSurface(mProjectedSurface, projected);
  return true;
}

template <class S>
void RecordedStealthProjectSurface::Record(S& aStream) const {
  WriteElement(aStream, mSurface);
  WriteElement(aStream, mProjectedSurface);
  WriteElement(aStream, mPremultiplied);
  WriteElement(aStream, mSeed);
  WriteElement(aStream, mEdgeTolerance);
}

template <class S>
RecordedStealthProjectSurface::RecordedStealthProjectSurface(S& aStream)
    : RecordedEventDerived(STEALTHPROJECTSURFACE) {
  ReadElement(aStream, mSurface);
  ReadElement(aStream, mProjectedSurface);
  ReadElement(aStream, mPremultiplied);
  ReadElement(aStream, mSeed);
  ReadElement(aStream, mEdgeTolerance);
}

inline void RecordedStealthProjectSurface::OutputSimpleEventInfo(
    std::stringstream& aStringStream) const {
  aStringStream << "[" << mSurface << "] Surface projected";
}

}  // namespace gfx
}  // namespace mozilla

// The list of recorded events RecordedEvent::DoWithEvent expands: Mozilla's
// own (FOR_EACH_EVENT_MOZILLA, the macro of RecordedEventImpl.h under the name
// our hook gives it) plus ours at the end. The cases of the switch it makes are
// distinct constants, so their order does not matter. Defined here, before
// Mozilla's macro exists: a macro is only expanded where it is used.
#define FOR_EACH_EVENT(f) \
  FOR_EACH_EVENT_MOZILLA(f) f(STEALTHPROJECTSURFACE, RecordedStealthProjectSurface);

#endif  // MOZILLA_GFX_STEALTHRECORDEDPROJECTION_H_
