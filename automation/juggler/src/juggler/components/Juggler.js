/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// Services is available as a global in XPCOM component context

// Load SimpleChannel in browser-process global.
Services.scriptloader.loadSubScript('resource://gre/modules/juggler/SimpleChannel.js');
const {Dispatcher} = ChromeUtils.importESModule("resource://gre/modules/juggler/protocol/Dispatcher.js");
const {BrowserHandler} = ChromeUtils.importESModule("resource://gre/modules/juggler/protocol/BrowserHandler.js");
const {NetworkObserver} = ChromeUtils.importESModule("resource://gre/modules/juggler/NetworkObserver.js");
const {TargetRegistry} = ChromeUtils.importESModule("resource://gre/modules/juggler/TargetRegistry.js");
const {EarlyProxyHold} = ChromeUtils.importESModule("resource://gre/modules/juggler/EarlyProxyHold.js");
const {say} = ChromeUtils.importESModule("resource://gre/modules/juggler/Say.js");
const {Helper} = ChromeUtils.importESModule('resource://gre/modules/juggler/Helper.js');
const {ActorManagerParent} = ChromeUtils.importESModule('resource://gre/modules/ActorManagerParent.sys.mjs');
const helper = new Helper();

const Cc = Components.classes;
const Ci = Components.interfaces;

// Register JSWindowActors that will be instantiated for each frame.
ActorManagerParent.addJSWindowActors({
  JugglerFrame: {
    parent: {
      esModuleURI: 'resource://gre/modules/juggler/JugglerFrameParent.sys.mjs',
    },
    child: {
      esModuleURI: 'resource://gre/modules/juggler/JugglerFrameChild.sys.mjs',
      events: {
        // Normally, we instantiate an actor when a new window is created.
        DOMWindowCreated: {},
        // However, for same-origin iframes, the navigation from about:blank
        // to the URL will share the same window, so we need to also create
        // an actor for a new document via DOMDocElementInserted.
        DOMDocElementInserted: {},
        // Also, listening to DOMContentLoaded.
        DOMContentLoaded: {},
        DOMWillOpenModalDialog: {},
        DOMModalDialogClosed: {},
        // A top-level document going into the back-forward cache, and coming
        // back from it (`persisted` on both): JugglerFrameChild.handleEvent.
        pagehide: {},
        pageshow: {},
      },
    },
    allFrames: true,
    safeForUntrustedWebProcess: true,
  },
});

let browserStartupFinishedCallback;
let browserStartupFinishedPromise = new Promise(x => browserStartupFinishedCallback = x);

export class Juggler {
  get classDescription() { return "Sample command-line handler"; }
  get classID() { return Components.ID('{f7a74a33-e2ab-422d-b022-4fb213dd2639}'); }
  get contractID() { return "@mozilla.org/remote/juggler;1" }
  get QueryInterface() {
    return ChromeUtils.generateQI([ Ci.nsICommandLineHandler, Ci.nsIObserver ]);
  }
  get helpInfo() {
    return "  --juggler            Enable Juggler automation\n";
  }

  handle(cmdLine) {
    // flag has to be consumed in nsICommandLineHandler:handle
    // to avoid issues on macos. See Marionette.jsm::handle() for more details.
    // TODO: remove after Bug 1724251 is fixed.
    cmdLine.handleFlag("juggler-pipe", false);
  }

  // This flow is taken from Remote agent and Marionette.
  // See https://github.com/mozilla-firefox/firefox/blob/35e22180b0b61413dd8eccf6c00b1c6fac073eee/remote/components/RemoteAgent.sys.mjs#L417
  async observe(subject, topic) {
    switch (topic) {
      case "profile-after-change":
        Services.obs.addObserver(this, "command-line-startup");
        Services.obs.addObserver(this, "browser-idle-startup-tasks-finished");
        break;
      case "command-line-startup":
        Services.obs.removeObserver(this, topic);
        const cmdLine = subject;
        const jugglerPipeFlag = cmdLine.handleFlag('juggler-pipe', false);
        if (!jugglerPipeFlag)
          return;
        TargetRegistry.markDriven();
        // The first point where the pipe flag is known: from here every proxied
        // channel is held until a command decides the road of the session. The
        // NetworkObserver (final-ui-startup) adopts this filter. If it cannot be
        // registered now the NetworkObserver registers its own, as before.
        try {
          this._earlyHold = EarlyProxyHold.register();
        } catch (e) {
          this._earlyHold = null;
          say('Juggler: early proxy hold not registered: ' + (e && e.message) + '\n');
        }

        this._silent = cmdLine.findFlag('silent', false) >= 0;
        if (this._silent) {
          Services.startup.enterLastWindowClosingSurvivalArea();
          browserStartupFinishedCallback();
        }
        Services.obs.addObserver(this, "final-ui-startup");
        break;
      case "browser-idle-startup-tasks-finished":
        browserStartupFinishedCallback();
        break;
      // Used to wait until the initial application window has been opened.
      case "final-ui-startup":
        Services.obs.removeObserver(this, topic);

        const targetRegistry = new TargetRegistry({ survivesLastWindow: this._silent });
        new NetworkObserver(targetRegistry, this._earlyHold);

        const loadStyleSheet = () => {
          if (Cc["@mozilla.org/gfx/info;1"].getService(Ci.nsIGfxInfo).isHeadless) {
            const styleSheetService = Cc["@mozilla.org/content/style-sheet-service;1"].getService(Components.interfaces.nsIStyleSheetService);
            const ioService = Cc["@mozilla.org/network/io-service;1"].getService(Components.interfaces.nsIIOService);
            const uri = ioService.newURI('resource://gre/modules/juggler/content/hidden-scrollbars.css', null, null);
            styleSheetService.loadAndRegisterSheet(uri, styleSheetService.AGENT_SHEET);
          }
        };

        // Force create hidden window here, otherwise its creation later closes the web socket!
        // Since https://phabricator.services.mozilla.com/D219834, hiddenDOMWindow is only available on MacOS.
        if (Services.appShell.hasHiddenWindow) {
          Services.appShell.hiddenDOMWindow;
        }

        // The first navigation of the client must see the CRLite deltas (and
        // the full filter) the core put in <profile>/security_state/.
        // cert_storage reads them on a thread of its own, in parallel to this
        // start; a page verified before it has finished could miss them.
        // StealthSecurityState.whenStorageReady()
        // (security/manager/ssl/stealth/StealthSecurityState.sys.mjs) resolves
        // when it has. So the client gets nothing of this browser until then:
        // no command reaches the dispatcher (receiveMessage below keeps them in
        // order), and the line that tells it the browser is ready is written
        // after. The promise is never rejected and never left pending; if the
        // module cannot be loaded there is nothing to wait for.
        let storageReady = false;
        const heldMessages = [];
        let whenStorageReady;
        try {
          whenStorageReady = ChromeUtils.importESModule("resource://gre/modules/psm/StealthSecurityState.sys.mjs").StealthSecurityState.whenStorageReady();
        } catch (e) {
          say('Juggler: the security state is not awaited: ' + (e && e.message) + '\n');
          whenStorageReady = Promise.resolve();
        }

        let pipeStopped = false;
        let browserHandler;
        const pipe = Cc['@mozilla.org/juggler/remotedebuggingpipe;1'].getService(Ci.nsIRemoteDebuggingPipe);
        const connection = {
          QueryInterface: ChromeUtils.generateQI([Ci.nsIRemoteDebuggingPipeClient]),
          receiveMessage(message) {
            if (!storageReady) {
              heldMessages.push(message);
              return;
            }
            if (this.onmessage)
              this.onmessage({ data: message });
          },
          disconnected() {
            if (browserHandler)
              browserHandler['Browser.close']();
          },
          send(message) {
            if (pipeStopped) {
              // We are missing the response to Browser.close,
              // but everything works fine. Once we actually need it,
              // we have to stop the pipe after the response is sent.
              return;
            }
            pipe.sendMessage(message);
          },
        };
        pipe.init(connection);
        const dispatcher = new Dispatcher(connection);
        browserHandler = new BrowserHandler(dispatcher.rootSession(), dispatcher, targetRegistry, browserStartupFinishedPromise, () => {
          if (this._silent)
            Services.startup.exitLastWindowClosingSurvivalArea();
          connection.onclose();
          pipe.stop();
          pipeStopped = true;
        });
        dispatcher.rootSession().setHandler(browserHandler);
        loadStyleSheet();
        await whenStorageReady;
        storageReady = true;
        for (const message of heldMessages.splice(0))
          connection.receiveMessage(message);
        // STEALTHFOX: Playwright declares the browser ready ONLY when it reads
        // this line on the process stdout (waitForReadyState looks for the exact
        // string 'Juggler listening to the pipe' in the browser logs).
        //
        // dump() in system modules goes through nsJSUtils::DumpEnabled(), which,
        // without DEBUG and without MOZ_ENABLE_JS_DUMP - neither of them defined in
        // a release build of ours - falls back to
        // browser.dom.window.dump.enabled, whose default in StaticPrefList
        // is @IS_NOT_MOZILLA_OFFICIAL@. With MOZILLA_OFFICIAL=1 it is FALSE, the
        // line is not written, and every launch times out while the pipe works
        // perfectly: no error anywhere.
        //
        // Measured on 2026-08-19 on the same binary, three arms: control
        // PASSES; only the pref turned off one line before -> TimeoutError with
        // PW_PIPE_READ/WRITE valid, pipe.init ok and 4 notifications out of 4; pref
        // off plus this remedy -> PASSES again.
        //
        // It is turned on ONLY around this line and put back exactly as it was
        // (clearUserPref if there was no user value), because a pref left
        // on for the whole session would be a divergence from retail. No
        // page exists yet at final-ui-startup, and window.dump returns
        // nothing different in the two states, so the window is not observable.
        const _dumpHadUserValue = Services.prefs.prefHasUserValue("browser.dom.window.dump.enabled");
        const _dumpVal = Services.prefs.getBoolPref("browser.dom.window.dump.enabled", false);
        Services.prefs.setBoolPref("browser.dom.window.dump.enabled", true);
        try {
          dump(`\nJuggler listening to the pipe\n`);
        } finally {
          if (_dumpHadUserValue) Services.prefs.setBoolPref("browser.dom.window.dump.enabled", _dumpVal);
          else Services.prefs.clearUserPref("browser.dom.window.dump.enabled");
        }
        break;
    }
  }

}

const jugglerInstance = new Juggler();

// This is used by the XPCOM codepath which expects a constructor
export var JugglerFactory = function() {
  return jugglerInstance;
};

