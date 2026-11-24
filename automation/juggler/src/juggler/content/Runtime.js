/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";
// Note: this file should be loadabale with eval() into worker environment.
// Avoid Components.*, ChromeUtils and global const variables.

if (!this.Debugger) {
  // Worker has a Debugger defined already.
  const {addDebuggerToGlobal} = ChromeUtils.importESModule("moz-src:///devtools/platform/jsdebugger.sys.mjs");
  addDebuggerToGlobal(Components.utils.getGlobalForObject(globalThis));
}

// ⛔ AN ID NAMES ONE OBJECT FOR THE WHOLE SESSION, NOT FOR ONE PROCESS.
//
// Every other id Juggler hands out is a UUID (Helper.generateId); these were
// a counter, and this file is loaded once per content process and once per
// worker, so every process counted id-1, id-2... from the start. A page that
// moves to another process - a document served with
// Cross-Origin-Opener-Policy and Cross-Origin-Embedder-Policy and the one
// after it, measured 2026-10-24 - had its new worlds named exactly as the old
// ones, in the same order: the utility world was id-8 in both, and a client
// still holding the old id-8 and an object of it (id-10) was answered by the
// new id-8 with "Cannot find object with id = id-10". A context id or an
// object id from a process that is gone can now only be unknown, which the
// engine already answers as such ("Failed to find execution context",
// "Cannot find object"); it can no longer name something else, and an
// element handle kept across the move can no longer reach a different node.
//
// Math.random, not Services or crypto: this file must load in a worker too
// (see the note at the top), and two draws give about 80 bits, so two
// processes of one session never share a prefix.
let idPrefix = Math.random().toString(36).slice(2, 10) + Math.random().toString(36).slice(2, 10);
let lastId = 0;
function generateId() {
  return 'id-' + idPrefix + '-' + (++lastId);
}

// Stealth: JSON stringify helper source, re-evaluated on debugger re-attach.
//
// (!) WE READ AND REWRITE THE DESCRIPTOR, NEVER THE PROPERTY. MEASURED, NOT
// ASSUMED. The previous version did:
//     const oldToJSON = Date.prototype?.toJSON;   // READ  -> calls the getter
//     Date.prototype.toJSON = undefined;          // WRITE -> calls the setter
//     ... Date.prototype.toJSON = oldToJSON;      // WRITE -> calls the setter
// If the PAGE has redefined `Date.prototype.toJSON` as an accessor, those three
// operations enter its code. The trap takes two lines:
//     Object.defineProperty(Date.prototype, 'toJSON', {get(){...}, set(v){...}})
// Measurement 2026-08-19: it records `get, set:undefined, set:function` for EVERY
// `evaluate` that returns a value and ZERO for one that does not serialize; six
// hits after the first, twelve after the second. It accumulates at every round.
//
// `getOwnPropertyDescriptor` does not invoke the getter and `defineProperty` does not
// invoke the setter, so none of the three operations touches the code of the
// page any more. The behaviour does not change: during serialization `toJSON` is
// a data property with value `undefined` as before, and at the end the original
// descriptor comes back identical, accessor included.
//
// The three natives are captured at the time of the `bind`, so a hook
// installed AFTER does not intercept them. Declared residue: a page that
// hooks `Object.defineProperty` BEFORE would still see us - it is a much
// more invasive hook, which breaks real sites, and it has not been measured.
const _STEALTH_JSON_STRINGIFY_SRC = `((stringify, getDesc, defProp, object) => {
  const EMPTY_DESC = {value: undefined, writable: true, enumerable: false, configurable: true};
  const dDate = getDesc(Date.prototype, 'toJSON');
  if (dDate)
    defProp(Date.prototype, 'toJSON', EMPTY_DESC);
  const dArray = getDesc(Array.prototype, 'toJSON');
  if (dArray)
    defProp(Array.prototype, 'toJSON', EMPTY_DESC);

  let hasSymbol = false;
  const result = stringify(object, (key, value) => {
    if (typeof value === 'symbol')
      hasSymbol = true;
    return value;
  });

  if (dDate)
    defProp(Date.prototype, 'toJSON', dDate);
  if (dArray)
    defProp(Array.prototype, 'toJSON', dArray);

  return hasSymbol ? undefined : result;
}).bind(null, JSON.stringify.bind(JSON), Object.getOwnPropertyDescriptor, Object.defineProperty)`;

const consoleLevelToProtocolType = {
  'dir': 'dir',
  'log': 'log',
  'debug': 'debug',
  'info': 'info',
  'error': 'error',
  'warn': 'warning',
  'dirxml': 'dirxml',
  'table': 'table',
  'trace': 'trace',
  'clear': 'clear',
  'group': 'startGroup',
  'groupCollapsed': 'startGroupCollapsed',
  'groupEnd': 'endGroup',
  'assert': 'assert',
  'profile': 'profile',
  'profileEnd': 'profileEnd',
  'count': 'count',
  'countReset': 'countReset',
  'time': null,
  'timeLog': 'timeLog',
  'timeEnd': 'timeEnd',
  'timeStamp': 'timeStamp',
};

const disallowedMessageCategories = new Set([
  'XPConnect JavaScript',
  'component javascript',
  'chrome javascript',
  'chrome registration',
  'XBL',
  'XBL Prototype Handler',
  'XBL Content Sink',
  'xbl javascript',
]);

class Runtime {
  constructor(isWorker = false) {
    this._debugger = new Debugger();
    // Stealth: skip Realm debug mode activation so the JS engine runs at full
    // speed (Ion JIT enabled, no slowPathOnNativeCall overhead). The Debugger
    // still tracks globals and executeInGlobal works — only the performance-
    // degrading debug instrumentation is skipped.
    this._debugger.stealthMode = true;
    this._pendingPromises = new Map();
    this._executionContexts = new Map();
    this._windowToExecutionContext = new Map();
    this._eventListeners = [];
    if (isWorker) {
      this._registerWorkerConsoleHandler();
    } else {
      this._registerConsoleServiceListener(Services);
      this._registerConsoleAPIListener(Services);
    }
    // We can't use event listener here to be compatible with Worker Global Context.
    // Use plain callbacks instead.
    this.events = {
      onConsoleMessage: createEvent(),
      onRuntimeError: createEvent(),
      onErrorFromWorker: createEvent(),
      onExecutionContextCreated: createEvent(),
      onExecutionContextDestroyed: createEvent(),
      onBindingCalled: createEvent(),
    };
  }

  executionContexts() {
    return [...this._executionContexts.values()];
  }

  async evaluate({executionContextId, expression, returnByValue}) {
    const executionContext = this.findExecutionContext(executionContextId);
    if (!executionContext)
      throw new Error('Failed to find execution context with id = ' + executionContextId);
    const exceptionDetails = {};
    let result = await executionContext.evaluateScript(expression, exceptionDetails);
    if (!result) {
      executionContext.throwIfItsWindowLeft();
      return {exceptionDetails};
    }
    if (returnByValue)
      result = executionContext.ensureSerializedToValue(result);
    return {result};
  }

  async callFunction({executionContextId, functionDeclaration, args, returnByValue}) {
    const executionContext = this.findExecutionContext(executionContextId);
    if (!executionContext)
      throw new Error('Failed to find execution context with id = ' + executionContextId);
    const exceptionDetails = {};
    let result = await executionContext.evaluateFunction(functionDeclaration, args, exceptionDetails);
    if (!result) {
      executionContext.throwIfItsWindowLeft();
      return {exceptionDetails};
    }
    if (returnByValue)
      result = executionContext.ensureSerializedToValue(result);
    return {result};
  }

  async getObjectProperties({executionContextId, objectId}) {
    const executionContext = this.findExecutionContext(executionContextId);
    if (!executionContext)
      throw new Error('Failed to find execution context with id = ' + executionContextId);
    return {properties: executionContext.getObjectProperties(objectId)};
  }

  async disposeObject({executionContextId, objectId}) {
    const executionContext = this.findExecutionContext(executionContextId);
    if (!executionContext)
      throw new Error('Failed to find execution context with id = ' + executionContextId);
    return executionContext.disposeObject(objectId);
  }

  _registerConsoleServiceListener(Services) {
    const Ci = Components.interfaces;
    const consoleServiceListener = {
      QueryInterface: ChromeUtils.generateQI([Ci.nsIConsoleListener]),

      observe: message => {
        if (!(message instanceof Ci.nsIScriptError) || !message.outerWindowID ||
            !message.category || disallowedMessageCategories.has(message.category)) {
          return;
        }
        const errorWindow = Services.wm.getOuterWindowWithId(message.outerWindowID);
        // Note: error locations are one-based, while console locations are zero-based in
        // Firefox.  We want to report all of them as zero-based.  Newer Playwright
        // clients read `pageError.location.url` strictly and crash when location
        // is undefined (issue #13).
        const errorLocation = {
          lineNumber: message.lineNumber - 1,
          columnNumber: message.columnNumber - 1,
          url: message.sourceName,
        };
        if (message.category === 'Web Worker' && message.logLevel === Ci.nsIConsoleMessage.error) {
          emitEvent(this.events.onErrorFromWorker, errorWindow, message.message, '' + message.stack, errorLocation);
          return;
        }
        const executionContext = this._windowToExecutionContext.get(errorWindow);
        if (!executionContext) {
          return;
        }
        const typeNames = {
          [Ci.nsIConsoleMessage.debug]: 'debug',
          [Ci.nsIConsoleMessage.info]: 'info',
          [Ci.nsIConsoleMessage.warn]: 'warn',
          [Ci.nsIConsoleMessage.error]: 'error',
        };
        if (!message.hasException) {
          emitEvent(this.events.onConsoleMessage, {
            args: [{
              value: message.message,
            }],
            type: typeNames[message.logLevel],
            executionContextId: executionContext.id(),
            location: {
              lineNumber: message.lineNumber,
              columnNumber: message.columnNumber,
              url: message.sourceName,
            },
          });
        } else {
          emitEvent(this.events.onRuntimeError, {
            executionContext,
            message: message.errorMessage,
            stack: message.stack ? message.stack.toString() : '',
            location: errorLocation,
          });
        }
      },
    };
    Services.console.registerListener(consoleServiceListener);
    this._eventListeners.push(() => Services.console.unregisterListener(consoleServiceListener));
  }

  _registerConsoleAPIListener(Services) {
    const Ci = Components.interfaces;
    const Cc = Components.classes;
    const ConsoleAPIStorage = Cc["@mozilla.org/consoleAPI-storage;1"].getService(Ci.nsIConsoleAPIStorage);
    const onMessage = ({ wrappedJSObject }) => {
      const executionContext = Array.from(this._executionContexts.values()).find(context => {
        // There is no easy way to determine isolated world context and we normally don't write
        // objects to console from utility worlds so we always return main world context here.
        if (context._isIsolatedWorldContext())
          return false;
        const domWindow = context._domWindow;
        try {
          // `windowGlobalChild` might be dead already; accessing it will throw an error, message in a console,
          // and infinite recursion.
          return domWindow && domWindow.windowGlobalChild.innerWindowId === wrappedJSObject.innerID;
        } catch (e) {
          return false;
        }
      });
      if (!executionContext)
        return;
      this._onConsoleMessage(executionContext, wrappedJSObject);
    }
    ConsoleAPIStorage.addLogEventListener(
      onMessage,
      Cc["@mozilla.org/systemprincipal;1"].createInstance(Ci.nsIPrincipal)
    );
    this._eventListeners.push(() => ConsoleAPIStorage.removeLogEventListener(onMessage));
  }

  _registerWorkerConsoleHandler() {
    setConsoleEventHandler(message => {
      const executionContext = Array.from(this._executionContexts.values())[0];
      this._onConsoleMessage(executionContext, message);
    });
    this._eventListeners.push(() => setConsoleEventHandler(null));
  }

  _onConsoleMessage(executionContext, message) {
    const type = consoleLevelToProtocolType[message.level];
    if (!type)
      return;
    const args = message.arguments.map(arg => executionContext.rawValueToRemoteObject(arg));
    emitEvent(this.events.onConsoleMessage, {
      args,
      type,
      executionContextId: executionContext.id(),
      location: {
        lineNumber: message.lineNumber - 1,
        columnNumber: message.columnNumber - 1,
        url: message.filename,
      },
    });
  }

  // A runtime that is disposed keeps nothing of the documents it served: its contexts hold their windows (and
  // their remote objects hold the page's objects), and the debugger holds its debuggees until it is told otherwise.
  dispose() {
    let failure = null;
    // Every listener is removed, even when one refuses: each of them holds this runtime, and with it the contexts.
    for (const tearDown of this._eventListeners) {
      try {
        tearDown.call(null);
      } catch (e) {
        failure = failure || { error: e };
      }
    }
    try {
      this._eventListeners = [];
      for (const context of [...this._executionContexts.values()]) {
        try {
          this.destroyExecutionContext(context);
        } catch (e) {
          dump('Runtime.dispose: a context failed to be destroyed: ' + e.message + '\n');
        }
      }
      this._executionContexts.clear();
      this._windowToExecutionContext.clear();
      this._pendingPromises.clear();
      this._debugger.removeAllDebuggees();
    } finally {
      if (failure)
        throw failure.error;
    }
  }

  async _awaitPromise(executionContext, obj, exceptionDetails = {}) {
    if (obj.promiseState === 'fulfilled')
      return {success: true, obj: obj.promiseValue};
    if (obj.promiseState === 'rejected') {
      const debuggee = executionContext._debuggee;
      exceptionDetails.text = debuggee.executeInGlobalWithBindings('e.message', {e: obj.promiseReason}, {useInnerBindings: true}).return;
      exceptionDetails.stack = debuggee.executeInGlobalWithBindings('e.stack', {e: obj.promiseReason}, {useInnerBindings: true}).return;
      return {success: false, obj: null};
    }
    // Stealth: onPromiseSettled requires Realm::isDebuggee() which we skip in
    // stealth mode. Track settlement via .then() on the content promise instead.
    // Also register in _pendingPromises so destroyExecutionContext can reject
    // if the page navigates before the promise settles (prevents hang).
    let resolve, reject;
    const promise = new Promise((a, b) => { resolve = a; reject = b; });
    const promiseID = obj.promiseID || generateId();
    this._pendingPromises.set(promiseID, {resolve: null, reject, executionContext, exceptionDetails});

    const rawPromise = obj.unsafeDereference();
    // NO `Cu.waiveXrays` HERE, AND THAT IS THE DIFFERENCE BETWEEN A NATIVE `then` AND
    // THE PAGE'S ONE.
    //
    // There used to be `Cu.waiveXrays(rawPromise).then(...)` here. The waiver removes the Xray,
    // so `.then` was resolved on the REAL prototype chain of the site: if
    // a page replaces `Promise.prototype.then`, its code was
    // run and could COUNT. Measured on 2026-08-23 with
    // an observable-crossings gate: an asynchronous `page.evaluate`
    // set off the trap **1 time out of 1**, and it was the only
    // crossing left in the whole flow.
    //
    // Without the waiver, `rawPromise` stays behind the Xray and `.then` resolves to the
    // NATIVE method, which the site cannot divert. The behaviour does not change:
    // `Promise.prototype.then` works on the internal slot, not on the prototype.
    // Verified on 7 cases - value, delay, object, already resolved promise,
    // chain of awaits, fetch, and the REJECTION with the message intact - 7 out of 7, and the
    // gate goes back to zero crossings.
    rawPromise.then(
      () => {
        this._pendingPromises.delete(promiseID);
        resolve({success: true, obj: obj.promiseValue});
      },
      () => {
        this._pendingPromises.delete(promiseID);
        try {
          const debuggee = executionContext._debuggee;
          exceptionDetails.text = debuggee.executeInGlobalWithBindings('e.message', {e: obj.promiseReason}, {useInnerBindings: true}).return;
          exceptionDetails.stack = debuggee.executeInGlobalWithBindings('e.stack', {e: obj.promiseReason}, {useInnerBindings: true}).return;
        } catch(e) {}
        resolve({success: false, obj: null});
      }
    );
    return await promise;
  }

  createExecutionContext(domWindow, contextGlobal, auxData, serializationGlobal) {
    // Note: domWindow is null for workers.
    const context = new ExecutionContext(this, domWindow, contextGlobal, auxData, serializationGlobal);
    this._executionContexts.set(context._id, context);
    if (domWindow)
      this._windowToExecutionContext.set(domWindow, context);
    emitEvent(this.events.onExecutionContextCreated, context);
    return context;
  }

  findExecutionContext(executionContextId) {
    const executionContext = this._executionContexts.get(executionContextId);
    if (!executionContext)
      throw new Error('Failed to find execution context with id = ' + executionContextId);
    return executionContext;
  }

  destroyExecutionContext(destroyedContext) {
    for (const [promiseID, {reject, executionContext}] of this._pendingPromises) {
      if (executionContext === destroyedContext) {
        reject(new Error('Execution context was destroyed!'));
        this._pendingPromises.delete(promiseID);
      }
    }
    // The debuggee is removed by the Debugger.Object that addDebuggee gave, not by the global it was given. The
    // global of the page's own world is its WindowProxy, and a WindowProxy follows the frame: once the frame has
    // gone to another process (an iframe of another site) the proxy here is a remote one, no longer a global object,
    // and `removeDebuggee(proxy)` throws "argument is not a global object" while the debuggee stays registered. The
    // throw stopped everything that destroyed the frame's contexts: the commit of the document that replaces the
    // page the frame was in (the navigation to the same address, whose document stays in this process, then never
    // told its document: it neither committed nor aborted) and the detach of the frame.
    this._debugger.removeDebuggee(destroyedContext._debuggee);
    if (destroyedContext._serializationGlobal)
      this._debugger.removeDebuggee(destroyedContext._serializationGlobal);
    this._executionContexts.delete(destroyedContext._id);
    if (destroyedContext._domWindow)
      this._windowToExecutionContext.delete(destroyedContext._domWindow);
    emitEvent(this.events.onExecutionContextDestroyed, destroyedContext);
  }
}

class ExecutionContext {
  constructor(runtime, domWindow, contextGlobal, auxData, serializationGlobal) {
    this._runtime = runtime;
    this._domWindow = domWindow;
    this._contextGlobal = contextGlobal;
    this._debuggee = runtime._debugger.addDebuggee(contextGlobal);
    // (!) WHERE WE SERIALIZE IS A DECISION, NOT A DETAIL.
    //
    // The return value of `evaluate` used to be serialized IN THE REALM OF THE
    // PAGE, and `JSON.stringify` reads `toJSON` on every value it touches: if the
    // site has put an accessor on `Object.prototype.toJSON`, those reads
    // are its own and it can COUNT them. Measured on 2026-08-23 on a normal flow:
    // click, `page.title()`, `page.content()`, the locators and an `evaluate` that
    // returns a number make **zero** crossings; an `evaluate` that returns
    // `{a:1, b:[1,2,3]}` makes **six** on `toJSON` plus **two** on
    // `Object.defineProperty`. They were the only observable crossing of the
    // whole flow.
    //
    // The two `defineProperty` were already a DECLARED residue in the comment of
    // `_STEALTH_JSON_STRINGIFY_SRC` ("a page that hooks Object.defineProperty
    // BEFORE would still see us - it has not been measured"). Now it is measured.
    //
    // The remedy is not to move `evaluate`: it is to serialize in a global that
    // is NOT the site's. From there an object of the page is read through
    // an Xray, which does not expose the prototype chain, so
    // `Object.prototype.toJSON` of the site does not exist for the one who serializes and the
    // getter does not fire. `wantXrays` here is not a choice: it is the mechanism.
    //
    // In the workers `serializationGlobal` is absent and we fall back on the global of the
    // context, which in the workers is already the only one there is.
    // (!) IT IS BUILT AT THE FIRST SERIALIZATION, NOT AT EVERY FRAME.
    //
    // Before, the global arrived already built, because it was an ARGUMENT: so
    // one more sandbox was born for every frame of every document, even where
    // nobody ever serialized anything. On a page with fifty iframes that is
    // fifty globals paid for nothing. Now a FACTORY arrives and it is called
    // at the first real use.
    //
    // `_ensureJsonStringify` was already lazy for a different and narrower
    // reason - not to touch the intrinsics before the first script of the page -
    // but the sandbox under it was not, so half of the cost remained.
    // (!) IT IS ALWAYS A FACTORY, never an already built global. The first draft
    // accepted both and told them apart with `typeof === 'function'`: a
    // parameter that means two different things depending on the type is exactly
    // what this project has already paid for once - `push_range` that
    // returned one or three tokens without saying so - and sooner or later someone reads it
    // the other way round. The workers pass none and fall back on their own
    // global, which there is the only one that exists.
    this._serializationGlobalFactory = serializationGlobal || null;
    this._serializationGlobal = null;
    this._serializationDebuggeeCache = null;
    this._remoteObjects = new Map();
    this._id = generateId();
    this._auxData = auxData;
    // STEALTHFOX: do NOT run any code in the page realm before the page's own
    // scripts. Building this JSON-stringify helper eagerly would touch page-realm
    // intrinsics (JSON / Date.prototype / Array.prototype) before the first page
    // script, an observable difference from a never-automated page. It is only
    // needed at serialization time (always post-page); build it lazily on first use.
    this._jsonStringifyObject = null;
  }

  // The debuggee of the serialization, resolved at first use. In the workers there is
  // no factory and we fall back on the global of the context, which there is the only
  // one that exists.
  _serializer() {
    if (!this._serializationDebuggeeCache) {
      const global = this._serializationGlobalFactory
          ? this._serializationGlobalFactory()
          : null;
      if (global) {
        this._serializationGlobal = global;
        this._serializationDebuggeeCache =
            this._runtime._debugger.addDebuggee(global);
      } else {
        this._serializationDebuggeeCache = this._debuggee;
      }
    }
    return this._serializationDebuggeeCache;
  }

  _ensureJsonStringify() {
    if (!this._jsonStringifyObject)
      this._jsonStringifyObject = this._serializer().executeInGlobal(_STEALTH_JSON_STRINGIFY_SRC).return;
    return this._jsonStringifyObject;
  }

  id() {
    return this._id;
  }

  auxData() {
    return this._auxData;
  }

  _isIsolatedWorldContext() {
    return !!this._auxData.name;
  }

  // An evaluation that raised in a world whose window has since left (the iframe was removed, or went to another
  // process) did not raise in the page: the engine's own read of the window found a cross-origin proxy or a closed
  // window ("Permission denied to access property "document" on cross-origin object", the first thing the injected
  // script reads of its window). That is not an exception of the page, to be returned as one: it is the context being
  // destroyed, the answer of every other command aimed at a context that went. The check runs only after an
  // exception, so a successful evaluation costs nothing and the page sees nothing of it.
  throwIfItsWindowLeft() {
    if (this._windowLeft())
      throw new Error('Execution context was destroyed!');
  }

  _windowLeft() {
    const window = this._domWindow;
    if (!window)
      return false;
    try {
      if (Cu.isRemoteProxy(window) || Cu.isDeadWrapper(window) || window.closed)
        return true;
      return !window.document;
    } catch (e) {
      return true;
    }
  }

  async evaluateScript(script, exceptionDetails = {}) {

    // Stealth: skip user gesture activation so content can't detect automation
    // via navigator.userActivation.isActive/hasBeenActive after evaluate.
    // Set zoom.stealth.juggler.user_gesture_in_evaluate=true to restore
    // original behavior (required for popups/fullscreen/autoplay via evaluate).
    let allowUserGesture = false;
    try { allowUserGesture = Services.prefs.getBoolPref("zoom.stealth.juggler.user_gesture_in_evaluate", false); } catch(e) {}
    const userInputHelper = (allowUserGesture && this._domWindow) ? this._domWindow.windowUtils.setHandlingUserInput(true) : null;
    if (allowUserGesture && this._domWindow && this._domWindow.document)
      this._domWindow.document.notifyUserGestureActivation();

    let {success, obj} = this._getResult(this._debuggee.executeInGlobal(script), exceptionDetails);
    userInputHelper && userInputHelper.destruct();
    if (!success)
      return null;
    if (obj && obj.isPromise) {
      const awaitResult = await this._runtime._awaitPromise(this, obj, exceptionDetails);
      if (!awaitResult.success)
        return null;
      obj = awaitResult.obj;
    }
    return this._createRemoteObject(obj);
  }

  evaluateScriptSafely(script) {

    try {
      this._debuggee.executeInGlobal(script);
    } catch (e) {
      dump(`WARNING: ${e.message}\n${e.stack}\n`);
    }
  }

  async evaluateFunction(functionText, args, exceptionDetails = {}) {

    const funEvaluation = this._getResult(this._debuggee.executeInGlobal('(' + functionText + ')'), exceptionDetails);
    if (!funEvaluation.success)
      return null;
    if (!funEvaluation.obj.callable)
      throw new Error('functionText does not evaluate to a function!');
    args = args.map(arg => {
      if (arg.objectId) {
        if (!this._remoteObjects.has(arg.objectId))
          throw new Error('Cannot find object with id = ' + arg.objectId);
        return this._remoteObjects.get(arg.objectId);
      }
      switch (arg.unserializableValue) {
        case 'Infinity': return Infinity;
        case '-Infinity': return -Infinity;
        case '-0': return -0;
        case 'NaN': return NaN;
        default: return this._toDebugger(arg.value);
      }
    });
    // Stealth: same gate as evaluateScript (see comment above).
    let allowUserGesture2 = false;
    try { allowUserGesture2 = Services.prefs.getBoolPref("zoom.stealth.juggler.user_gesture_in_evaluate", false); } catch(e) {}
    const userInputHelper = (allowUserGesture2 && this._domWindow) ? this._domWindow.windowUtils.setHandlingUserInput(true) : null;
    if (allowUserGesture2 && this._domWindow && this._domWindow.document)
      this._domWindow.document.notifyUserGestureActivation();
    let {success, obj} = this._getResult(funEvaluation.obj.apply(null, args), exceptionDetails);
    userInputHelper && userInputHelper.destruct();
    if (!success)
      return null;
    if (obj && obj.isPromise) {
      const awaitResult = await this._runtime._awaitPromise(this, obj, exceptionDetails);
      if (!awaitResult.success)
        return null;
      obj = awaitResult.obj;
    }
    return this._createRemoteObject(obj);
  }

  addBinding(name, script) {
    Cu.exportFunction((...args) => {
      let payload = args[0];
      // A FUNCTION IS NOT A MESSAGE: it is the page-side end of the binding, which the script of the binding hands over so
      // that the client can answer a call later without a name on the page's window. It is kept as an object of this
      // context (the client calls it with Runtime.callFunction and the objectId) and the event carries only its id.
      // Anything else is the message, as before.
      if (typeof payload === 'function')
        payload = { bindingEnd: this.rawValueToRemoteObject(payload).objectId };
      emitEvent(this._runtime.events.onBindingCalled, {
        executionContextId: this._id,
        name,
        payload,
      });
    }, this._contextGlobal, {
      defineAs: name,
    });
    // STEALTHFOX: not enumerable.
    //
    // exportFunction creates the property ENUMERABLE, so it ended up inside
    // for..in and Object.keys(window): the cheapest scan a site can
    // do. What passes here is the internal TRANSPORT of Playwright, not the name
    // the user has chosen (that one is created by the controller injected on the
    // JavaScript side), so hiding it does not change any API.
    //
    // It stays visible to getOwnPropertyNames, and it cannot be otherwise: the
    // page must be able to call it. Measured on 2026-08-24: a normal launch
    // never gets here, only whoever calls expose_function does.
    // (!) WITHOUT THE XRAY. The first draft read the descriptor from the wrapped
    // global, and the Xray does not let the underlying property be touched: measured,
    // the controller became non-enumerable (that one is defined by the injected JS,
    // on the content side) and the channel stayed inside Object.keys.
    // The waiver is needed to operate on the real object, and holds only here: the
    // property we have just created ourselves, it is not the site's.
    try {
      const bare = Cu.waiveXrays(this._contextGlobal);
      const descr = Object.getOwnPropertyDescriptor(bare, name);
      if (descr && descr.enumerable) {
        descr.enumerable = false;
        Object.defineProperty(bare, name, descr);
      }
    } catch (e) {}
    this.evaluateScriptSafely(script);
  }

  unsafeObject(objectId) {
    if (!this._remoteObjects.has(objectId))
      return;
    return { object: this._remoteObjects.get(objectId).unsafeDereference() };
  }

  rawValueToRemoteObject(rawValue) {

    const debuggerObj = this._debuggee.makeDebuggeeValue(rawValue);
    return this._createRemoteObject(debuggerObj);
  }

  _instanceOf(debuggerObj, rawObj, className) {
    if (this._domWindow)
      return rawObj instanceof this._domWindow[className];
    return this._debuggee.executeInGlobalWithBindings('o instanceof this[className]', {o: debuggerObj, className: this._debuggee.makeDebuggeeValue(className)}, {useInnerBindings: true}).return;
  }

  _createRemoteObject(debuggerObj) {
    if (debuggerObj instanceof Debugger.Object) {
      const objectId = generateId();
      this._remoteObjects.set(objectId, debuggerObj);
      const rawObj = debuggerObj.unsafeDereference();
      const type = typeof rawObj;
      let subtype = undefined;
      if (debuggerObj.isProxy)
        subtype = 'proxy';
      else if (Array.isArray(rawObj))
        subtype = 'array';
      else if (Object.is(rawObj, null))
        subtype = 'null';
      else if (typeof Node !== 'undefined' && Node.isInstance(rawObj))
        subtype = 'node';
      else if (this._instanceOf(debuggerObj, rawObj, 'RegExp'))
        subtype = 'regexp';
      else if (this._instanceOf(debuggerObj, rawObj, 'Date'))
        subtype = 'date';
      else if (this._instanceOf(debuggerObj, rawObj, 'Map'))
        subtype = 'map';
      else if (this._instanceOf(debuggerObj, rawObj, 'Set'))
        subtype = 'set';
      else if (this._instanceOf(debuggerObj, rawObj, 'WeakMap'))
        subtype = 'weakmap';
      else if (this._instanceOf(debuggerObj, rawObj, 'WeakSet'))
        subtype = 'weakset';
      else if (this._instanceOf(debuggerObj, rawObj, 'Error'))
        subtype = 'error';
      else if (this._instanceOf(debuggerObj, rawObj, 'Promise'))
        subtype = 'promise';
      else if ((this._instanceOf(debuggerObj, rawObj, 'Int8Array')) || (this._instanceOf(debuggerObj, rawObj, 'Uint8Array')) ||
               (this._instanceOf(debuggerObj, rawObj, 'Uint8ClampedArray')) || (this._instanceOf(debuggerObj, rawObj, 'Int16Array')) ||
               (this._instanceOf(debuggerObj, rawObj, 'Uint16Array')) || (this._instanceOf(debuggerObj, rawObj, 'Int32Array')) ||
               (this._instanceOf(debuggerObj, rawObj, 'Uint32Array')) || (this._instanceOf(debuggerObj, rawObj, 'Float32Array')) ||
               (this._instanceOf(debuggerObj, rawObj, 'Float64Array'))) {
        subtype = 'typedarray';
      }
      return {objectId, type, subtype};
    }
    if (typeof debuggerObj === 'symbol') {
      const objectId = generateId();
      this._remoteObjects.set(objectId, debuggerObj);
      return {objectId, type: 'symbol'};
    }

    let unserializableValue = undefined;
    if (Object.is(debuggerObj, NaN))
      unserializableValue = 'NaN';
    else if (Object.is(debuggerObj, -0))
      unserializableValue = '-0';
    else if (Object.is(debuggerObj, Infinity))
      unserializableValue = 'Infinity';
    else if (Object.is(debuggerObj, -Infinity))
      unserializableValue = '-Infinity';
    return unserializableValue ? {unserializableValue} : {value: debuggerObj};
  }

  ensureSerializedToValue(protocolObject) {
    if (!protocolObject.objectId)
      return protocolObject;
    const obj = this._remoteObjects.get(protocolObject.objectId);
    this._remoteObjects.delete(protocolObject.objectId);
    return {value: this._serialize(obj)};
  }

  _toDebugger(obj) {
    if (typeof obj !== 'object')
      return obj;
    if (obj === null)
      return obj;
    const properties = {};
    for (let [key, value] of Object.entries(obj)) {
      properties[key] = {
        configurable: true,
        writable: true,
        enumerable: true,
        value: this._toDebugger(value),
      };
    }
    const baseObject = Array.isArray(obj) ? '([])' : '({})';
    const debuggerObj = this._debuggee.executeInGlobal(baseObject).return;
    debuggerObj.defineProperties(properties);
    return debuggerObj;
  }

  _serialize(obj) {
    const result = this._serializer().executeInGlobalWithBindings('stringify(e)', {e: obj, stringify: this._ensureJsonStringify()}, {useInnerBindings: true});
    if (result.throw)
      throw new Error('Object is not serializable');
    return result.return === undefined ? undefined : JSON.parse(result.return);
  }

  disposeObject(objectId) {
    this._remoteObjects.delete(objectId);
  }

  getObjectProperties(objectId) {
    if (!this._remoteObjects.has(objectId))
      throw new Error('Cannot find object with id = ' + arg.objectId);
    const result = [];
    for (let obj = this._remoteObjects.get(objectId); obj; obj = obj.proto) {
      for (const propertyName of obj.getOwnPropertyNames()) {
        const descriptor = obj.getOwnPropertyDescriptor(propertyName);
        if (!descriptor.enumerable)
          continue;
        result.push({
          name: propertyName,
          value: this._createRemoteObject(descriptor.value),
        });
      }
    }
    return result;
  }

  _getResult(completionValue, exceptionDetails = {}) {
    if (!completionValue)
      throw new Error('evaluation terminated');
    if (completionValue.throw) {
      if (this._debuggee.executeInGlobalWithBindings('e instanceof Error', {e: completionValue.throw}, {useInnerBindings: true}).return) {
        exceptionDetails.text = this._debuggee.executeInGlobalWithBindings('e.message', {e: completionValue.throw}, {useInnerBindings: true}).return;
        exceptionDetails.stack = this._debuggee.executeInGlobalWithBindings('e.stack', {e: completionValue.throw}, {useInnerBindings: true}).return;
      } else {
        exceptionDetails.value = this._serialize(completionValue.throw);
      }
      return {success: false, obj: null};
    }
    return {success: true, obj: completionValue.return};
  }
}

const listenersSymbol = Symbol('listeners');

function createEvent() {
  const listeners = new Set();
  const subscribeFunction = listener => {
    listeners.add(listener);
    return () => listeners.delete(listener);
  }
  subscribeFunction[listenersSymbol] = listeners;
  return subscribeFunction;
}

function emitEvent(event, ...args) {
  let listeners = event[listenersSymbol];
  if (!listeners || !listeners.size)
    return;
  listeners = new Set(listeners);
  for (const listener of listeners)
    listener.call(null, ...args);
}

// Export Runtime to global.
globalThis.Runtime = Runtime;
