// The network WebRTC gathers on is declared by the core, never read from the host (nr_stealth_network.h). Mozilla's code
// that reads the host stays in the tree, as it is in the tag, and is made unreachable at its only entry. These checks
// assert THAT ENTRY, so a second one added by a later Mozilla version fails them (the behaviour is asserted by the gtests
// of the suite StealthDeclaredNetwork, which the candidate's filter runs):
//
//   * the interfaces: the OS enumerators (addrs-win32, addrs-netlink, addrs-bsd) define stun_getaddrs_filtered, and
//     nothing calls it: nr_stun_get_addrs asks the declaration (nr_stealth_declared_addrs); no other source of the
//     transport tree reads the adapters of the host;
//   * the default address: the route probe (nr_ice_get_default_address) has one caller, nr_ice_get_default_local_address,
//     whose first statement is the guard that answers; that function is called only by nr_ice_set_local_addresses;
//   * the host UDP ports: the socket factory of every NrIceCtx calls nr_socket_local_create, which is ours; the body of
//     Mozilla's function, renamed, is called by it alone.
//
// Run: node --test juggler/tests/*.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const TREE = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const TRANSPORT = 'dom/media/webrtc/transport';
const STUN = TRANSPORT + '/third_party/nICEr/src/stun/';
const read = rel => fs.readFileSync(path.join(TREE, rel), 'utf8');
const MARK = '// STEALTH-HOOK(fingerprint/webrtc/declared-network)';

// Every C and C++ source and header of the transport tree that exists in this checkout.
const sources = [];
const walk = dir => {
  const abs = path.join(TREE, dir);
  if (!fs.existsSync(abs)) return;
  for (const entry of fs.readdirSync(abs, { withFileTypes: true })) {
    const rel = dir + '/' + entry.name;
    if (entry.isDirectory()) walk(rel);
    else if (/\.(c|cc|cpp|h|mm)$/.test(entry.name)) sources.push(rel);
  }
};
walk(TRANSPORT);
const filesMentioning = re => sources.filter(rel => re.test(read(rel))).sort();

const ENUMERATORS = ['bsd', 'netlink', 'netlink-wireless', 'win32']
  .flatMap(os => [STUN + 'addrs-' + os + '.cpp', STUN + 'addrs-' + os + '.h'])
  .filter(rel => fs.existsSync(path.join(TREE, rel)));

test('the OS enumerators are in the tree, and only they name stun_getaddrs_filtered: nothing calls it', () => {
  // nr_stun_get_addrs (addrs.cpp) does not call it, so the enumerators never run; a caller added by a later Mozilla
  // version, anywhere, is a file in this list.
  assert.equal(ENUMERATORS.length, 7, 'the enumerators are in the tree, as in the tag: the code that must not run is the code that is there');
  const named = filesMentioning(/\bstun_getaddrs_filtered\b/);
  for (const rel of named) assert.ok(ENUMERATORS.includes(rel), rel + ' names stun_getaddrs_filtered');
  assert.doesNotMatch(read(STUN + 'addrs.cpp'), /\bstun_getaddrs_filtered\b/);
});

test('no other source of the transport tree reads the adapters of the host', () => {
  const readers = filesMentioning(/\b(GetAdaptersAddresses|getifaddrs|NETLINK_ROUTE|RTM_GETADDR)\b/);
  for (const rel of readers) assert.ok(ENUMERATORS.includes(rel), rel + ' reads the adapters of the host');
});

test('nr_stun_get_addrs asks the declaration, in one line, and nothing else of nICEr does', () => {
  const addrs = read(STUN + 'addrs.cpp');
  assert.equal(addrs.split('\n').filter(l => l === '    _status = nr_stealth_declared_addrs(addrs, maxaddrs, count);  ' + MARK).length, 1);
  const callers = filesMentioning(/\bnr_stealth_declared_addrs\s*\(/)
    .filter(rel => !rel.startsWith(TRANSPORT + '/test/') && rel !== TRANSPORT + '/nr_stealth_network.cpp');
  assert.deepEqual(callers, [STUN + 'addrs.cpp', STUN + 'nr_stealth_addrs.h', TRANSPORT + '/nr_stealth_network.h'].sort());
});

test('the route probe has one caller, whose first statement is the guard; that caller is called by nr_ice_set_local_addresses only', () => {
  const text = read(TRANSPORT + '/third_party/nICEr/src/ice/ice_ctx.cpp');
  assert.equal(text.match(/\bnr_ice_get_default_address\s*\(/g).length, 2, 'the definition and one call');
  const fn = text.match(/static int nr_ice_get_default_local_address\([^)]*\)\n  \{\n([\s\S]*?)\n  \}\n/)[1];
  assert.match(fn,
    /^    int r,_status;\n    nr_transport_addr default_addr;\n    int i;\n\n    if \(int rv; nr_stealth_default_local_address_guard\(ctx, ip_version, addrs, addr_ct, addrp, &rv\)\) return rv;  \/\/ STEALTH-HOOK\(fingerprint\/webrtc\/declared-network\)\n\n    if \(\(r=nr_ice_get_default_address\(ctx, ip_version, &default_addr\)\)\)/);
  // Its callers: the three of nr_ice_set_local_addresses, none elsewhere.
  const setter = text.slice(text.indexOf('int nr_ice_set_local_addresses('), text.indexOf('int nr_ice_set_target_for_default_local_address_lookup('));
  const total = text.match(/\bnr_ice_get_default_local_address\s*\(/g).length;
  const inSetter = setter.match(/\bnr_ice_get_default_local_address\s*\(/g).length;
  assert.equal(inSetter, 3);
  assert.equal(total, inSetter + 1, 'the definition and the three calls of nr_ice_set_local_addresses');
  // The family of the page's server is chosen in the guard, so the argument at the call is Mozilla's.
  assert.match(setter, /ctx, ctx->target_for_default_local_address_lookup->ip_version,\n/);
  assert.doesNotMatch(setter, /nr_stealth_/);
});

test('nr_socket_local_create is ours, and the body of Mozilla\'s function is called by it alone', () => {
  const own = read(TRANSPORT + '/nr_stealth_network.cpp');
  assert.equal(own.match(/\nint nr_socket_local_create\(/g).length, 1);
  assert.ok(own.includes('StealthPorts().NextAvailable('), 'the ports of the connection');
  const mozilla = read(TRANSPORT + '/nricectx.cpp');
  assert.doesNotMatch(mozilla, /\nint nr_socket_local_create\(/);
  assert.match(mozilla, /\nint nr_socket_local_create_Mozilla\(void\* obj, nr_transport_addr\* addr,  \/\/ STEALTH-HOOK\(fingerprint\/webrtc\/declared-network\)\n/);
  // The context's socket factory names the function that is ours (nr_socket_local.h declares it).
  assert.match(mozilla, /ctx_socket_factory_vtbl = \{nr_socket_local_create,/);
  const callers = filesMentioning(/\bnr_socket_local_create_Mozilla\b/).sort();
  assert.deepEqual(callers, [TRANSPORT + '/nr_stealth_network.cpp', TRANSPORT + '/nr_stealth_network.h', TRANSPORT + '/nricectx.cpp']);
  // Nobody else takes a port of the connection: the one entry is the wrapper.
  assert.deepEqual(filesMentioning(/\bStealthPorts\s*\(/).filter(rel => !rel.startsWith(TRANSPORT + '/test/')),
    [TRANSPORT + '/nr_stealth_network.cpp', TRANSPORT + '/nricectx.h']);
});
