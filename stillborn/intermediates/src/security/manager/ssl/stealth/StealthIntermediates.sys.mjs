/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The intermediate certificates of Mozilla's list come from a file the core
// declares, never from the network.
//
// A retail Firefox holds, a few minutes into its first session, the whole
// "security-state/intermediates" collection of Remote Settings: it downloads
// it once the browser is idle (RemoteSecuritySettings.init, browser-idle-
// startup), after the first navigation. A page can tell the two states apart,
// because a chain that only the preloaded intermediate completes verifies in
// one and fails in the other. So the engine never creates that collection (the
// hook in RemoteSecuritySettings.sys.mjs: ownsPreloads) and the same list is
// written into cert_storage before any window, from the file whose path the
// core declares in the pref below. The list is the one the core fetched and
// pinned (format, collection timestamp, set hash); this module only reads it.
//
// No request is ever made from here: the file is read with nsIFile and a
// synchronous stream (IOUtils is asynchronous only, and the point is to be
// done before the first window exists), parsed, and handed to
// nsICertStorage.addCerts, exactly as RemoteSecuritySettings hands the
// downloaded certificates (same nsICertInfo shape, TRUST_INHERIT). Any error
// is one line in the console and nothing else: a browser that starts without
// the list is a browser that verifies like a fresh profile, not a broken one.

const PREF_FILE = "zoom.stealth.intermediates.file";
const FORMAT = 1;

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  NetUtil: "resource://gre/modules/NetUtil.sys.mjs",
});

class CertInfo {
  constructor(cert, subject) {
    this.cert = cert;
    this.subject = subject;
    this.trust = Ci.nsICertStorage.TRUST_INHERIT;
  }
}
CertInfo.prototype.QueryInterface = ChromeUtils.generateQI(["nsICertInfo"]);

function readFileSync(path) {
  const file = Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);
  file.initWithPath(path);
  const stream = Cc[
    "@mozilla.org/network/file-input-stream;1"
  ].createInstance(Ci.nsIFileInputStream);
  stream.init(file, -1, -1, 0);
  try {
    return lazy.NetUtil.readInputStreamToString(stream, stream.available(), {
      charset: "UTF-8",
    });
  } finally {
    stream.close();
  }
}

export const StealthIntermediates = {
  // What the last load did, for the test and for whoever debugs a profile:
  // { path, readMs, parseMs, addCertsMs, count, result, doneMs, done }.
  // result is "" until addCerts calls back, then its nsresult (a number);
  // "skipped" when the pref is empty, "error: ..." when something threw.
  // done is a promise that settles when the write to cert_storage has ended.
  lastLoad: null,

  // The engine never creates the Remote Settings collection of intermediates,
  // with or without the pref: the list is declared, not downloaded.
  ownsPreloads() {
    return true;
  },

  /**
   * Reads the declared list and writes it to cert_storage. Synchronous up to
   * the call to addCerts, which dispatches the write to cert_storage's own
   * thread and returns; the callback settles lastLoad.done.
   *
   * @param {string} [path] a file to read instead of the one the pref names
   * @returns {object} the record that is also stored in lastLoad
   */
  load(path) {
    const record = {
      path: "",
      readMs: 0,
      parseMs: 0,
      addCertsMs: 0,
      count: 0,
      result: "",
      doneMs: 0,
      done: Promise.resolve(),
    };
    this.lastLoad = record;
    try {
      record.path =
        path ?? Services.prefs.getStringPref(PREF_FILE, "");
      if (!record.path) {
        record.result = "skipped";
        return record;
      }

      let t0 = ChromeUtils.now();
      const text = readFileSync(record.path);
      let t1 = ChromeUtils.now();
      record.readMs = t1 - t0;

      const list = JSON.parse(text);
      if (list.format !== FORMAT || !Array.isArray(list.certs)) {
        throw new Error("unknown format of the intermediates list");
      }
      const infos = [];
      for (const entry of list.certs) {
        if (entry && entry.cert && entry.subject) {
          infos.push(new CertInfo(entry.cert, entry.subject));
        }
      }
      let t2 = ChromeUtils.now();
      record.parseMs = t2 - t1;
      record.count = infos.length;

      const certStorage = Cc["@mozilla.org/security/certstorage;1"].getService(
        Ci.nsICertStorage
      );
      record.done = new Promise(resolve => {
        certStorage.addCerts(infos, rv => {
          record.result = rv;
          record.doneMs = ChromeUtils.now() - t2;
          if (rv != Cr.NS_OK) {
            console.error("StealthIntermediates: addCerts failed: " + rv);
          }
          resolve(rv);
        });
      });
      record.addCertsMs = ChromeUtils.now() - t2;
    } catch (e) {
      record.result = "error: " + e;
      console.error("StealthIntermediates: " + e);
    }
    return record;
  },
};

// The component the profile-after-change category creates (components.conf):
// the list is in cert_storage before any window, so before any verification a
// page can cause.
export function StealthIntermediatesStartup() {}

StealthIntermediatesStartup.prototype = {
  QueryInterface: ChromeUtils.generateQI(["nsIObserver"]),
  observe(subject, topic) {
    if (topic == "profile-after-change") {
      StealthIntermediates.load();
    }
  },
};
