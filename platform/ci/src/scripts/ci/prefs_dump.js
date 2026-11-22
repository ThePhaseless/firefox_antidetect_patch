/* eslint-disable no-undef */
// scripts/ci/prefs_dump.js - every preference the packaged engine has at startup of a fresh profile, for `xpcshell_run.py prefs`.
//
//   firefox -xpcshell -g <gre> -a <gre>/browser -f prefs_dump.js -e "quit(0);"
//
// with the leg's environment (xpcshell_run.environment) and PREFS_DUMP_OUT, the path of the JSON to write. Nothing here is a test: it reads the
// preference service and writes what it holds, and the comparison between two engines is done in Python (prefs-compare), never here.
//
// What is enumerated, and from which branch:
//   default  getDefaultBranch("").getChildList("") - every name the default branch lists; one counts only when the typed getter of the DEFAULT branch
//            returns a value (a name that has only a user value makes the default getter throw: it is skipped here and is in "user"). Each entry is
//            {type, value, locked}: type "string" | "int" | "bool", the value as the typed getter returns it (getStringPref, getIntPref,
//            getBoolPref), locked = prefIsLocked(name).
//   user     getBranch("").getChildList("") filtered by prefHasUserValue(name): the user branch after the profile is announced to the service
//            (the same notification head.js sends in do_get_profile, with an EMPTY profile folder: no prefs.js, no user.js). Each entry {type, value}.
// A name whose type is PREF_INVALID or whose getter throws for another reason is written with type "invalid" / "error" and the message, so that it is
// a difference when the other engine does not have it, never a quiet omission.
//
// The profile is announced the way head.js does (a directory provider for ProfD and friends, then "profile-do-change"), and nothing else is
// notified: no profile-after-change, no startup of services that a page can not see.

// One function: the shell's global scope is shared with whatever the shell defines.
(function prefsDump() {
  const env = Cc["@mozilla.org/process/environment;1"].getService(Ci.nsIEnvironment);
  const outPath = env.get("PREFS_DUMP_OUT");
  if (!outPath) {
    throw new Error("PREFS_DUMP_OUT is not set");
  }
  const profilePath = env.get("XPCSHELL_TEST_PROFILE_DIR");
  if (!profilePath) {
    throw new Error("XPCSHELL_TEST_PROFILE_DIR is not set");
  }

  (function announceProfile() {
    const profile = Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);
    profile.initWithPath(profilePath);
    const provider = {
      getFile(prop, persistent) {
        persistent.value = true;
        if (prop == "ProfD" || prop == "ProfLD" || prop == "ProfDS" || prop == "ProfLDS") {
          return profile.clone();
        }
        return null;
      },
      QueryInterface: ChromeUtils.generateQI(["nsIDirectoryServiceProvider"]),
    };
    Services.dirsvc.QueryInterface(Ci.nsIDirectoryService).registerProvider(provider);
    Services.obs.notifyObservers(null, "profile-do-change", "xpcshell-do-get-profile");
  })();

  const root = Services.prefs;
  const defaults = Services.prefs.getDefaultBranch("");

  function typed(branch, name) {
    switch (branch.getPrefType(name)) {
      case Ci.nsIPrefBranch.PREF_STRING:
        return { type: "string", value: branch.getStringPref(name) };
      case Ci.nsIPrefBranch.PREF_INT:
        return { type: "int", value: branch.getIntPref(name) };
      case Ci.nsIPrefBranch.PREF_BOOL:
        return { type: "bool", value: branch.getBoolPref(name) };
      default:
        return { type: "invalid", value: null };
    }
  }

  const dump = { schema: 1, default: {}, user: {}, meta: { noDefaultValue: [] } };

  for (const name of defaults.getChildList("")) {
    let entry;
    try {
      entry = typed(defaults, name);
    } catch (e) {
      // NS_ERROR_UNEXPECTED: the name has no default value (a user value only); it is in "user" below
      if (e.result == Cr.NS_ERROR_UNEXPECTED) {
        dump.meta.noDefaultValue.push(name);
        continue;
      }
      entry = { type: "error", value: String(e) };
    }
    try {
      entry.locked = root.prefIsLocked(name);
    } catch (e) {
      entry.locked = "error: " + String(e);
    }
    dump.default[name] = entry;
  }

  for (const name of root.getChildList("")) {
    if (!root.prefHasUserValue(name)) {
      continue;
    }
    let entry;
    try {
      entry = typed(root, name);
    } catch (e) {
      entry = { type: "error", value: String(e) };
    }
    dump.user[name] = entry;
  }
  dump.meta.noDefaultValue.sort();

  // ASCII only on the wire (a \uXXXX for everything else), so that the bytes written do not depend on an encoder the shell does not have.
  const text = JSON.stringify(dump).replace(
    /[^\x20-\x7e]/g,
    c => "\u" + c.charCodeAt(0).toString(16).padStart(4, "0")
  );
  const file = Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);
  file.initWithPath(outPath);
  const stream = Cc["@mozilla.org/network/file-output-stream;1"].createInstance(Ci.nsIFileOutputStream);
  // PR_WRONLY | PR_CREATE_FILE | PR_TRUNCATE
  stream.init(file, 0x02 | 0x08 | 0x20, 0o644, 0);
  stream.write(text, text.length);
  stream.close();
  print("PREFS_DUMP_OK default=" + Object.keys(dump.default).length + " user=" + Object.keys(dump.user).length);
})();
