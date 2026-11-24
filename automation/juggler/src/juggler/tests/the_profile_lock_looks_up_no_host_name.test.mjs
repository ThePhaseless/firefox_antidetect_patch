// The profile lock looks up no host name.
//
// On Unix nsProfileLock::LockWithSymlink writes an address into the signature of its symlink lock. Mozilla takes it
// from PR_GetHostByName(the machine's own host name) unless MOZ_PROXY_BYPASS_PROTECTION is set: a lookup made at
// start-up, before any proxy is decided, through the system resolver, carrying the machine's name to the network
// (seen by the resolver trap of the realness suite on a runner whose name is not in /etc/hosts). Windows takes another
// lock and makes no such lookup. The file is as Mozilla wrote it: the block is already under that symbol, and one line of
// the moz.build of the directory defines it, so the signature keeps 127.0.0.1, as Mozilla's own MOZ_PROXY_BYPASS_PROTECTION
// build does; nothing else of that build is taken (no other source of the directory reads the symbol).
//
// Run: node --test juggler/tests/*.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const LOCK = 'toolkit/profile/nsProfileLock.cpp';

test('the lookup of the host name in the symlink lock is compiled out for the directory by the define of its moz.build, and the only reader of the symbol is that block', () => {
  const text = fs.readFileSync(path.join(ROOT, LOCK), 'utf8').replace(/\r\n/g, '\n');
  // The file is as Mozilla wrote it: the block that looks up the host name is inside #ifndef MOZ_PROXY_BYPASS_PROTECTION.
  assert.doesNotMatch(text, /STEALTH-HOOK|#\s*if 0/);
  const open = text.indexOf('#  ifndef MOZ_PROXY_BYPASS_PROTECTION\n');
  assert.ok(open >= 0, 'the block that looks up the host name is not under the symbol');
  const close = text.indexOf('#  endif', open);
  const block = text.slice(open, close);
  assert.match(block, /PR_GetSystemInfo\(PR_SI_HOSTNAME/);
  assert.match(block, /PR_GetHostByName\(hostname/);
  // Outside that block the file asks for no host name and no lookup.
  const rest = text.slice(0, open) + text.slice(close);
  assert.doesNotMatch(rest, /PR_GetHostByName|PR_SI_HOSTNAME|gethostbyname|getaddrinfo/);
  // The signature still starts from the loopback address.
  assert.match(text.slice(0, open), /inaddr\.s_addr = htonl\(INADDR_LOOPBACK\);/);
  // The symbol is defined for the sources of that directory, by one line of its moz.build.
  const build = fs.readFileSync(path.join(ROOT, 'toolkit/profile/moz.build'), 'utf8');
  assert.match(build, /\]\nDEFINES\["MOZ_PROXY_BYPASS_PROTECTION"\] = True  # STEALTH-HOOK\(network\/doh\)\n/);
  // The only entry: no other source of the directory reads the symbol, so the define changes nothing else.
  const readers = fs.readdirSync(path.join(ROOT, 'toolkit/profile'))
      .filter(f => /\.(cpp|h|mm|c)$/.test(f))
      .filter(f => fs.readFileSync(path.join(ROOT, 'toolkit/profile', f), 'utf8').includes('MOZ_PROXY_BYPASS_PROTECTION'));
  assert.deepEqual(readers, ['nsProfileLock.cpp']);
});
