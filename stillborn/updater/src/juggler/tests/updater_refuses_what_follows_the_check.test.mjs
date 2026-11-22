// The update system is the retail's (build/moz.configure/update-programs.configure
// is Mozilla's), and our own file, toolkit/mozapps/update/StealthUpdate.sys.mjs,
// refuses what follows an answer of the update server: no offered update is
// taken, nothing is downloaded, no scheduled task is left on the host.
//
// Three parts: the heads of the two functions that carry a guard, run from the
// real text of Mozilla's files on stubs (with a negative control each), the
// entry guards (the only parse, the only start of a download, the only
// registration of the task), and a behaviour check of our functions on stubs.
//
// Run: node --test juggler/tests/*.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const TREE = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const UPDATE = path.join(TREE, 'toolkit/mozapps/update');
const read = rel => fs.readFileSync(path.join(TREE, rel), 'utf8');

test('the update programs are configured as Mozilla wrote them', () => {
  const text = read('build/moz.configure/update-programs.configure');
  assert.doesNotMatch(text, /STEALTH/);
  assert.match(text, /"--enable-updater",\n\s+default=updater_default,/);
  assert.match(text, /"--enable-maintenance-service",/);
  assert.match(text, /"--disable-update-agent",/);
  const mozconfig = read('.mozconfig');
  assert.match(mozconfig, /^export MAR_CHANNEL_ID=firefox-mozilla-release$/m);
  assert.match(mozconfig, /^export ACCEPTED_MAR_CHANNEL_IDS=firefox-mozilla-release$/m);
  assert.doesNotMatch(mozconfig, /^ac_add_options --disable-(updater|maintenance-service|update-agent)/m);
});

// The head of a function, cut out of the real text of Mozilla's file at the
// first statement of Mozilla's that follows what the hooks put there, and run
// on stubs: what the function does before Mozilla's own code starts.
function head(rel, header, firstOfMozilla) {
  const text = read(rel);
  const start = text.indexOf(header);
  assert.ok(start > 0, `${header} is gone`);
  const end = text.indexOf(firstOfMozilla, start);
  assert.ok(end > start, `${firstOfMozilla} is gone`);
  return text.slice(start + header.length, end);
}

function runHead(body, { cutGuard = false, update, thisArg = {} } = {}) {
  let src = body;
  if (cutGuard) {
    // The negative control: the same head with the guard cut out.
    const cut = src.replace(
      /if \(StealthUpdate\.\w+\([^)]*\)\) (\{[^}]*\}|return[^;]*;)[^\n]*\n/, '');
    assert.notEqual(cut, src, 'no guard to cut');
    src = cut;
  }
  const { m } = load();
  const sandbox = {
    StealthUpdate: m,
    Components: { Exception: (msg, result) => ({ result }) },
    Cr: { NS_ERROR_NULL_POINTER: 0x80004003 },
    Ci: { nsIApplicationUpdateService: { DOWNLOAD_FAILURE_GENERIC: 'GENERIC' } },
  };
  const fn = vm.runInNewContext(`(async function (update, taskId) {${src}\n})`, sandbox);
  return fn.call(thisArg, update, 'task');
}

const DOWNLOAD_HEAD = ['toolkit/mozapps/update/UpdateService.sys.mjs',
  '  async #downloadUpdate(update) {',
  "    // Don't download the update if the update's version is less than the"];
const TASK_HEAD = ['toolkit/mozapps/update/BackgroundUpdate.sys.mjs',
  '  async _registerBackgroundUpdateTask(taskId = this.taskId) {',
  '    let binary = Services.dirsvc.get("XREExeF", Ci.nsIFile);'];

// The part of CheckerService.#updateCheck that turns the server's answer into
// updates, cut out of the real text and run on stubs: from `let updates;` to
// the log line that uses them. Private names become members of `this`.
function checkPart({ cutHook = false } = {}) {
  const text = read('toolkit/mozapps/update/UpdateService.sys.mjs');
  const start = text.indexOf('    let updates;\n    try {');
  const end = text.indexOf('    LOG(\n      "CheckerService:#updateCheck - number of updates available: "', start);
  assert.ok(start > 0 && end > start, "Mozilla's parse of the answer is gone");
  let src = text.slice(start, end)
    .replace(/this\.#parseUpdates\(/g, 'this.parse(')
    .replace(/this\.#getChannelStatus\(/g, 'this.status(')
    .replace(/this\.#getCheckFailedObject\(/g, 'this.failed(');
  if (cutHook) {
    const cut = src.replace(/StealthUpdate\.noneOffered\((.*)\);/, '$1;');
    assert.notEqual(cut, src, 'no hook to cut');
    src = cut;
  }
  const { m } = load();
  return vm.runInNewContext(
    `(function (request) {\n${src}\nreturn updates;\n})`,
    { StealthUpdate: m, LOG() {} });
}

const answerOf = parse => ({
  parse, status: () => 0, failed: (s, code) => ({ failed: code }),
});

test('whatever the answer offered, the check reports none', () => {
  const offered = [{ id: 1 }, { id: 2 }];
  const out = checkPart().call(answerOf(() => offered), {});
  assert.equal(out.length, 0);
  assert.equal(offered.length, 2, 'the parsed array is left alone');
});

test('an answer that cannot be parsed is still a failed check, as Mozilla made it', () => {
  const out = checkPart().call(answerOf(() => { throw new Error('xml'); }), {});
  assert.deepEqual({ ...out }, { failed: 200 });
});

test("negative control: without the hook the offered updates reach Mozilla's code", () => {
  const offered = [{ id: 1 }];
  const out = checkPart({ cutHook: true }).call(answerOf(() => offered), {});
  assert.equal(out, offered);
});

test("the only parse of the server's answer is the one the check uses", () => {
  const text = read('toolkit/mozapps/update/UpdateService.sys.mjs');
  // A second parse that Mozilla adds to a new version would hand updates to
  // code that noneOffered never sees.
  const calls = text.split('\n').filter(l => /this\.#parseUpdates\(/.test(l));
  assert.equal(calls.length, 1, 'a second parse of the answer');
});

test("a download of an update is refused after Mozilla's null check, no update still throws", async () => {
  const body = head(...DOWNLOAD_HEAD);
  assert.equal(await runHead(body, { update: {} }), 'GENERIC');
  await assert.rejects(runHead(body, { update: null }), e => e.result === 0x80004003);
  await assert.rejects(runHead(body, { update: undefined }), e => e.result === 0x80004003);
});

test("negative control: without the guard an update goes on into Mozilla's code", async () => {
  const body = head(...DOWNLOAD_HEAD);
  assert.equal(await runHead(body, { update: {}, cutGuard: true }), undefined);
});

test('the only start of a download is the end of #downloadUpdate', () => {
  const text = read('toolkit/mozapps/update/UpdateService.sys.mjs');
  const door = text.indexOf('  async #downloadUpdate(update) {');
  assert.ok(door > 0, "Mozilla's #downloadUpdate is gone");
  const calls = [...text.matchAll(/this\._downloader\.downloadUpdate\(/g)].map(m => m.index);
  assert.equal(calls.length, 1, 'a second way to start a download');
  assert.ok(calls[0] > door, 'the download starts outside #downloadUpdate');
  // Nothing between the door and the start declares another function.
  assert.equal(/\n  (async )?#?\w+\(.*\) \{\n/.test(text.slice(door + 10, calls[0])), false);
});

test("the background update task is not registered, nothing of Mozilla's runs first", async () => {
  const body = head(...TASK_HEAD);
  // No Services, no Ci: Mozilla's statements would throw if they ran.
  assert.equal(await runHead(body, { thisArg: { taskId: 't' } }), null);
});

test("negative control: without the guard the task is registered by Mozilla's code", async () => {
  const body = head(...TASK_HEAD);
  assert.equal(await runHead(body, { cutGuard: true }), undefined);
});

test('the only registration of the task is after the guard', () => {
  const text = read('toolkit/mozapps/update/BackgroundUpdate.sys.mjs');
  const fn = text.indexOf('  async _registerBackgroundUpdateTask(taskId = this.taskId) {');
  assert.ok(fn > 0, "Mozilla's _registerBackgroundUpdateTask is gone");
  const registers = [...text.matchAll(/TaskScheduler\.registerTask\(/g)].map(m => m.index);
  assert.equal(registers.length, 1, 'a second place registers a task');
  assert.ok(registers[0] > fn + text.slice(fn).indexOf('StealthUpdate.refusesHostTask()'));
});

test('the update cadence is the release one', () => {
  const prefs = read('browser/branding/unofficial/pref/firefox-branding.js');
  for (const [name, value] of [['app.update.interval', '21600'],
                               ['app.update.checkInstallTime.days', '63'],
                               ['app.update.promptWaitTime', '691200'],
                               ['app.update.badgeWaitTime', '345600']]) {
    const lines = prefs.split('\n').filter(l => l.startsWith(`pref("${name}",`));
    assert.equal(lines.length, 1, `${name} declared ${lines.length} times`);
    assert.ok(lines[0].startsWith(`pref("${name}", ${value});`), lines[0]);
  }
});

function load() {
  let src = fs.readFileSync(path.join(UPDATE, 'StealthUpdate.sys.mjs'), 'utf8');
  src = src.replace(/^export /gm, '');
  src += '\nmodule.exports = { noneOffered, refusesDownload, refusesHostTask };\n';
  const logged = [];
  const sandbox = { module: { exports: {} }, console: { info: m => logged.push(m) } };
  vm.runInNewContext(src, sandbox);
  return { m: sandbox.module.exports, logged };
}

test('our functions: none offered, every download and task refused', () => {
  const { m, logged } = load();
  const offered = [{}, {}];
  const out = m.noneOffered(offered);
  assert.equal(out.length, 0);
  assert.notEqual(out, offered, 'a new array, the parsed one untouched');
  assert.equal(offered.length, 2);
  assert.equal(logged.length, 1);
  assert.equal(m.noneOffered([]).length, 0);
  assert.equal(logged.length, 1, 'nothing to say when nothing was offered');
  assert.equal(m.refusesDownload(), true);
  assert.equal(m.refusesHostTask(), true);
});
