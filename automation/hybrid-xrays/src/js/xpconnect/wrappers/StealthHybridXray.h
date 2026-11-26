/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 2 -*- */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// STEALTHFOX [B322]: hybrid Xrays and the caller's objects. Declarations only;
// the definitions are in StealthHybridXray.cpp. Included by the files that use
// them (WrapperFactory.cpp, StealthSandbox.h, StealthHybridXray.cpp).

#ifndef StealthHybridXray_h
#define StealthHybridXray_h

#include "mozilla/Maybe.h"

#include "js/Class.h"               // JS::ObjectOpResult
#include "js/PropertyDescriptor.h"  // JS::PropertyDescriptor
#include "js/RootingAPI.h"
#include "js/TypeDecls.h"  // JS::HandleObject, JS::MutableHandleIdVector, ...
#include "js/Wrapper.h"    // js::CrossCompartmentWrapper

#include "XrayWrapper.h"

class JSObject;

// For HybridXrayWrapper, which walks its prototypes itself [B322]. A member of
// Mozilla's xpc::XrayWrapper, defined here by its qualified name (a definition
// of a member of xpc may stand in a namespace that encloses xpc).
template <typename Base, typename Traits>
constexpr xpc::XrayWrapper<Base, Traits>::XrayWrapper(unsigned flags,
                                                      bool aHasPrototype)
    : Base(flags | xpc::WrapperFactory::IS_XRAY_WRAPPER_FLAG, aHasPrototype) {}

// Every function and class of ours is in mozilla, never in xpc or another
// namespace of Mozilla's.
namespace mozilla {

// STEALTHFOX [B322]: HYBRID XRAYS, the view the CALLER'S world has of the page.
//
// The caller's world is a sandbox with the page's principal in which
// `page.evaluate` and the other ways of running the caller's code run. Its
// name lookups follow one rule: THE BROWSER'S OWN APIS ARE THE ORIGINAL ONES,
// AND WHAT THE PAGE ADDED IS THE PAGE'S. Applied level by level of the page's
// own prototype chain (ChainLookup in StealthHybridXray.cpp): a STANDARD level
// (a WebIDL object, the window, a standard prototype or constructor) answers
// with its native view, a level the PAGE CREATED (an instance, a class's
// prototype) with its own properties. A name some standard level knows goes to
// the first page-created level defining it before that level, else to the
// native definition; what the page added ON a standard level does not count for
// it. A name no standard level knows is the page's, looked up as the page looks
// it up. So `document.querySelector` is the native method even when the page
// replaced `Document.prototype.querySelector` (or set its own on `document`)
// with a Proxy that counts its callers, while `window.__NEXT_DATA__`,
// `el.__vue__`, a page class's `toString` and `valueOf`, a custom element's
// `click` and a page function called by its bare name are the page's.
//
// Neither existing view does both. A plain Xray (the utility world's) hides
// what the page added, so `window.__APP_STATE__` reads undefined; the
// transparent view (the page's own realm, where this code used to run) walks
// through every replacement the page made. A JS membrane cannot be the
// fallback either: the invariants of scripted proxies force the raw value on
// non-configurable properties, and WebIDL refuses a scripted Proxy as `this`.
// Here, in the wrapper itself, neither constraint applies.
//
// What that means trap by trap:
//  - has/get/set: the rule above (ChainLookup); a name the rule leaves to the
//    page reaches the page's object, and `set` reaches the page for every
//    name whose answer is not an accessor, so `window.x = 1` is seen by it.
//  - getOwnPropertyDescriptor and ownPropertyKeys: the standard own view
//    joined with the page's own properties, so `Object.keys(el)` lists the
//    expandos a framework put on the node.
//  - defineProperty, delete and the prototype and extensibility traps: the
//    page's object, as the page sees it, so `instanceof` with the page's
//    classes holds.
//  - call, construct, class name: the Xray's.
// The explicit page view stays `.wrappedJSObject`, as for every Xray.
//
// The other direction is not an Xray at all: the page reads the caller's
// objects through CallerObjectWrapper (StealthHybridXray.cpp), transparent for
// their own properties, with the caller's standard prototypes shown as the
// page's own. The two share a principal, so nothing is granted that the caller
// could not already take with a waiver, and only privileged code can create
// such a compartment (Juggler is the one that does).
template <typename Traits>
class HybridXrayWrapper
    : public xpc::XrayWrapper<js::CrossCompartmentWrapper, Traits> {
  using Base = xpc::XrayWrapper<js::CrossCompartmentWrapper, Traits>;

 public:
  constexpr explicit HybridXrayWrapper(unsigned flags)
      : Base(flags, /* aHasPrototype = */ false) {}

  virtual bool getOwnPropertyDescriptor(
      JSContext* cx, JS::Handle<JSObject*> wrapper, JS::Handle<jsid> id,
      JS::MutableHandle<mozilla::Maybe<JS::PropertyDescriptor>> desc)
      const override;
  virtual bool defineProperty(JSContext* cx, JS::Handle<JSObject*> wrapper,
                              JS::Handle<jsid> id,
                              JS::Handle<JS::PropertyDescriptor> desc,
                              JS::ObjectOpResult& result) const override;
  virtual bool ownPropertyKeys(JSContext* cx, JS::Handle<JSObject*> wrapper,
                               JS::MutableHandleIdVector props) const override;
  virtual bool delete_(JSContext* cx, JS::Handle<JSObject*> wrapper,
                       JS::Handle<jsid> id,
                       JS::ObjectOpResult& result) const override;
  virtual bool enumerate(JSContext* cx, JS::Handle<JSObject*> wrapper,
                         JS::MutableHandleIdVector props) const override;
  virtual bool getPrototype(JSContext* cx, JS::HandleObject wrapper,
                            JS::MutableHandleObject protop) const override;
  virtual bool setPrototype(JSContext* cx, JS::HandleObject wrapper,
                            JS::HandleObject proto,
                            JS::ObjectOpResult& result) const override;
  virtual bool setImmutablePrototype(JSContext* cx, JS::HandleObject wrapper,
                                     bool* succeeded) const override;
  virtual bool preventExtensions(JSContext* cx, JS::Handle<JSObject*> wrapper,
                                 JS::ObjectOpResult& result) const override;
  virtual bool isExtensible(JSContext* cx, JS::Handle<JSObject*> wrapper,
                            bool* extensible) const override;
  virtual bool has(JSContext* cx, JS::Handle<JSObject*> wrapper,
                   JS::Handle<jsid> id, bool* bp) const override;
  virtual bool get(JSContext* cx, JS::Handle<JSObject*> wrapper,
                   JS::HandleValue receiver, JS::Handle<jsid> id,
                   JS::MutableHandle<JS::Value> vp) const override;
  virtual bool set(JSContext* cx, JS::Handle<JSObject*> wrapper,
                   JS::Handle<jsid> id, JS::Handle<JS::Value> v,
                   JS::Handle<JS::Value> receiver,
                   JS::ObjectOpResult& result) const override;
  virtual bool hasOwn(JSContext* cx, JS::Handle<JSObject*> wrapper,
                      JS::Handle<jsid> id, bool* bp) const override;
  virtual bool getOwnEnumerablePropertyKeys(
      JSContext* cx, JS::Handle<JSObject*> wrapper,
      JS::MutableHandleIdVector props) const override;

  // The native view of this one object: the Xray's own resolution of it,
  // which ChainLookup asks of every standard level.
  bool nativeOwnPropertyDescriptor(
      JSContext* cx, JS::Handle<JSObject*> wrapper, JS::Handle<jsid> id,
      JS::MutableHandle<mozilla::Maybe<JS::PropertyDescriptor>> desc) const;

  static const HybridXrayWrapper singleton;
};

#define HybridXrayDOM mozilla::HybridXrayWrapper<xpc::DOMXrayTraits>
#define HybridXrayJS mozilla::HybridXrayWrapper<xpc::JSXrayTraits>

extern template class HybridXrayDOM;
extern template class HybridXrayJS;

bool IsHybridXrayWrapper(JSObject* obj);

// A BARE name of the caller's code, which reaches the page's window through
// the sandbox's prototype proxy. Resolved in the order the page's own realm
// resolves it, inside the same rule: the standard definition first, then a
// binding the page declared at its top level with let, const or class (its
// global lexical environment: not a property of the window, so `window.name`
// does not find it, in the page or here), then the window's properties.
bool HybridXrayGetBareName(
    JSContext* cx, JS::HandleObject wrapper, JS::HandleId id,
    JS::MutableHandle<mozilla::Maybe<JS::PropertyDescriptor>> desc);

// STEALTHFOX [B322]: whether the compartment WrapperFactory::Rewrap makes a
// wrapper for forces Xrays on what it reads: Gecko's `wantXrays`, or the
// caller's world (`hybridXrays`), which wants Xrays when IT reads the page but
// does not impose them on the page reading ITS objects (the page sees those
// transparently, as it saw them when the caller's code ran in the page's own
// realm). Hence the target's term is `wantXrays || hybridXrays` while the
// origin's stays Gecko's `wantXrays`. The context realm is the compartment
// read.
bool StealthTargetWantsXrays(JSContext* aCx, bool aWantXrays);

// Whether the context realm (the target of the wrapper) is a caller's world.
bool StealthTargetIsHybrid(JSContext* aCx);

// The same question for a realm given (DEBUG_CheckUnwrapSafety checks the
// wrapper Rewrap made, for the target realm it was made for): wantXrays or a
// caller's world.
bool StealthRealmWantsXrays(JS::Realm* aRealm, bool aWantXrays);

// STEALTHFOX [B322]: a caller's object, read by the page it shares a
// principal with. It goes BEFORE the web-object case in Rewrap, which would
// otherwise take it: the two compartments are same-origin and neither
// forces Xrays on the other, so that case hands the page a plain
// transparent wrapper, an object of another realm. A page that does not
// subsume the caller, or that wants Xrays (another sandbox), still gets
// what Gecko's rules give it.
//
// The four values it is decided from are Rewrap's own locals, which a hook
// cannot pass to a branch of the chain: StealthNoteCallerObject takes them
// where Rewrap has computed them (an anchor, after `sameOrigin`, on the one
// straight path every call takes before the chain) and decides then.
//
// The branch is not written into the chain. It would come between Mozilla's
// cross-origin case and its web-object case, so the web-object case steps
// aside for it: its first term goes through StealthNotCallerObject, which is
// that term unless a decision is waiting (it only looks, it takes nothing),
// and the regular case at the end of the chain, which is then the one reached,
// hands the page the caller's wrapper through StealthSelectedWrapper, which
// takes the decision (StealthCallerObjectApplies answers with it and clears it:
// a read with no decision since the last read is false). What the regular case
// computes before that (the flags, the Xray type, SelectWrapper's choice among
// static wrappers) reads nothing of the page and has no effect, and the
// wrapper it ends with is the one the branch gave. The decision is kept per
// thread: Rewrap runs on the thread of the context, and nothing between the
// anchor and the take (the conditions of the cases before it read the class of
// `obj` and two flags) reaches another Rewrap.
void StealthNoteCallerObject(JS::Realm* origin, JS::Realm* target,
                             bool targetIsChrome, bool targetSubsumesOrigin);
bool StealthNotCallerObject(bool aMozillaCondition);
bool StealthCallerObjectApplies();

// The parts of the pair, for a test with no Realm: the decision as a function
// of its five values, and the per-thread state it is kept in.
bool StealthCallerObjectDecision(bool aOriginHybrid, bool aTargetHybrid,
                                 bool aTargetWantsXrays, bool aTargetIsChrome,
                                 bool aTargetSubsumesOrigin);
void StealthRecordCallerObject(bool aApplies);

// The wrapper the page reads the caller's objects through (see the class
// comment in StealthHybridXray.cpp).
const js::Wrapper* StealthCallerObjectWrapper();

// STEALTHFOX [B322]: what the caller's world reads the page through. A hybrid
// Xray where the object has a standard view, and the transparent wrapper
// where it has none (a scripted Proxy, a generator): there the standard view
// would be empty, so the page's answer is the only one. The rule is written
// above HybridXrayWrapper in this file.
const js::Wrapper* StealthHybridWrapper(xpc::XrayType xrayType);

// STEALTHFOX [B322]: the wrapper Rewrap selects for a generic cross-compartment
// reference. aMozillaWrapper is what Gecko's SelectWrapper chose (a pure choice
// among static wrappers, it reads nothing and has no effect). When the context
// realm is a caller's world the answer is the hybrid Xray, for the references
// that are neither a security wrapper nor a waived Xray; Gecko's choice names
// them: the permissive Xray of a DOM object, of a JS object (each has its hybrid
// twin), and the permissive opaque Xray and the transparent wrapper of a
// reference with no Xray (both the transparent wrapper, as StealthHybridWrapper
// gives for them). Every other choice (the waived Xray, the opaque filters of
// the security wrappers) is Gecko's own answer, and so is every choice when the
// realm is not a caller's world. Before all that, a decision that
// StealthNoteCallerObject left waiting (see above) is taken here: the wrapper
// is the one the page reads the caller's objects through.
const js::Wrapper* StealthSelectedWrapper(JSContext* aCx,
                                          const js::Wrapper* aMozillaWrapper);

}  // namespace mozilla

#endif  // StealthHybridXray_h
