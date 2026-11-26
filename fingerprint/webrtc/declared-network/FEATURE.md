# fingerprint/webrtc/declared-network

Category: build, other, spoof
Prefs: none (the declaration is the environment variable STEALTHFOX_WEBRTC_NETWORK, read where the interfaces are enumerated)
Test: StealthDeclaredNetwork.* (dom/media/webrtc/transport/test/gtest/TestStealthDeclaredNetwork.cpp and TestStealthDeclaredNetworkBirth.cpp
(the default address with no socket made; the host ports of a connection through nr_socket_local_create; the responder starts on the loopback
whatever list Mozilla built: TheResponderStartsOnTheLoopbackWhateverListMozillaBuilt), in the default gtest filter of
the candidate); the cargo test mdns_service::stealth_tests::stealth_responder_on_the_loopback_hears_its_own_query; wrapper:tests/test_declared_host_network_e2e.py::test_two_connections_on_one_page_connect_in_the_time_of_retail (two connections on one page connect in under the responder's first retry: the hooks of `StunAddrsRequestParent.cpp` and `lib.rs` make the responder start on the loopback and hear itself); the mtransport unit tests gather on a declared adapter (test/gtest_utils.h, test/nr_stealth_test_network.h); the node tests
juggler/tests/ipv6_is_one_fact_of_the_declared_network.test.mjs and
juggler/tests/the_host_network_is_read_nowhere_and_ports_are_the_connections.test.mjs (the only entries of the host reads)

## What it does

The network WebRTC gathers on is declared by the core, never read from the host.

- R1, the interfaces. `nr_stun_get_addrs` returns the declared adapter: one private IPv4 address of a LAN (RFC 1918) and, with
  `v6=1` and a global unicast `/64` prefix of the exit, a temporary IPv6 address on the same adapter (an interface identifier
  drawn at random once per process, RFC 4941). `v6=1` without a prefix is no IPv6. Without a declaration, or with one that does
  not parse, there is no interface and an error in the log: never a fallback to the host. The OS enumerators (addrs-win32,
  addrs-netlink, addrs-netlink-wireless, addrs-bsd) are in the tree and built as in the tag, and nothing calls them:
  `nr_stun_get_addrs` asks `nr_stealth_declared_addrs` where Mozilla calls `stun_getaddrs_filtered` (its memset and its log loop
  run as Mozilla's). The node test asserts that no source names `stun_getaddrs_filtered` but the enumerators, and that no other
  source of the transport tree reads the adapters of the host.
- R2, the default route. The default address of a family is the declared entry of that family; there is no route probe (no socket
  connected to the page's server or to a public address, no getsockname): Mozilla's `nr_ice_get_default_address` stays in the file and
  never runs, because the first statement of `nr_ice_get_default_local_address` is the guard `nr_stealth_default_local_address_guard`
  (nr_stealth_addrs.h; it always answers). A family the declaration does not have has no default
  address. A declared machine without a family asks for the family it has (`nr_stealth_default_family`): a page reached over IPv6 on
  a machine declared without IPv6 gets the IPv4 default address (the family of the page's server is a property of the real network
  path, which the declared machine hides; measured on the firefox-63 candidate, Windows, direct: with no default address of the target's
  family the gathering found no address at all). That choice is made in the guard and only when the context has a target for the lookup
  (`nr_ice_set_target_for_default_local_address_lookup`; the call of `nr_ice_set_local_addresses` that has one passes the target's family,
  as Mozilla writes it): the two calls without a target ask for IPv4 and for IPv6 as they are, so a request for IPv6 on a machine without
  IPv6 has no answer, never the IPv4 address. When there is no address at all the gathering fails as upstream does.
- IPv6 is one fact, the declared network's. The same parse decides `network.dns.disableIPv6` in the parent (`StealthApplyDeclaredIPFamily`,
  once, at the top of `nsIOService::Init`): no IPv6 interface declared means no AAAA lookup in any process, so a page is never loaded over
  IPv6 while ICE says there is none. It is a default value (never written to the profile, the user value cleared); with no declaration, or one
  that does not parse, nothing is touched. The answer is the parser's own (`nr_stealth_declared_has_ipv6`, quiet), never a second reading. An IPv6 literal in an address, which needs no lookup, fails like a host with no IPv6 route (network/ipv6-literal).
- R3, the sockets. A host UDP socket binds the wildcard of its family on a port of its connection and reports the declared address
  with that port. The ports are consecutive in the order the sockets are made, from a base drawn at random in 49152-65535 for each
  connection, as Windows hands them out; a port another socket holds, or one the system keeps (Windows reserves ranges of the dynamic
  range and answers "access denied"), is skipped, and the search goes through the whole range (`StealthHostPorts::NextAvailable`). The
  connection's counter is a member of `NrIceCtx` (`host_ports_`, drawn at random by the default constructor of `StealthHostPorts`, when the
  context is constructed). `nr_socket_local_create` is ours (nr_stealth_network.cpp): the nICEr socket factory of every context calls it
  (`ctx_socket_factory_vtbl`); for a host UDP socket of a declared address (a connection, UDP, neither wildcard nor loopback) it copies the
  address with the next port of the connection and runs Mozilla's function, renamed `nr_socket_local_create_Mozilla`, whole on it, once per
  try, until the answer is not R_ALREADY (16384 busy ports are R_ALREADY, a copy that fails is R_INTERNAL); every other call goes straight to
  Mozilla's body with the address it was given. The port is registered as the last step of `NrSocket::create`, so a create that aborts
  leaves nothing in the set. A datagram between two sockets of this process goes on the
  kernel's loopback while each end sees the other's declared address (`StealthOwnPorts`); a server on localhost keeps its address.
- mDNS. The parent's responder joins the group on the loopback and sends through it (`nr_stealth_mdns_interfaces`: the list is the
  declaration, whose address the OS does not own, so a join on it fails and the responder would never hear its own query; stealth_interface.rs
  sets, after Mozilla's join loop, the multicast interface to the address it joined on: a query would otherwise leave on the default multicast route and never come
  back to its socket, and on Linux a join on 127.0.0.1 hears nothing without it, captures/mdns-loopback/loopback-join of
  invisible_WebRTC), so the query and the answer for our own .local names make the same round trip as on a real adapter; the names
  answer with the declared address.
- The mtransport unit tests gather on a declared adapter: `MtransportTest::SetUp` calls `StealthDeclareTestNetwork()` after `NR_reg_init()`, which sets
  STEALTHFOX_WEBRTC_NETWORK to a one-adapter declaration when the environment has none. The variable is read when the interfaces are
  enumerated and by `StealthApplyDeclaredNetwork` at the first `nsIOService::Init`; neither runs inside what `SetUp` did before the
  declaration (`MtransportTestUtils` gets the socket transport service, whose `Init` does not create the IO service).

## Hooks in Mozilla files

Each is one line with the marker; the forms are those of STRUCTURE.md.

- `third_party/nICEr/src/stun/addrs.cpp`: our include in a block of ours after util.h (registration), and
  `_status = nr_stealth_declared_addrs(addrs, maxaddrs, count);` where Mozilla calls `stun_getaddrs_filtered` (call wrap, G29: the
  called name changes, the arguments are Mozilla's). The include block of the OS enumerators is Mozilla's, as in the tag.
- `third_party/nICEr/src/ice/ice_ctx.cpp`: our include (registration) and the guard
  `if (int rv; nr_stealth_default_local_address_guard(ctx, ip_version, addrs, addr_ct, addrp, &rv)) return rv;` after the declarations
  of `nr_ice_get_default_local_address` (the first statement; the route probe and the comparison loop below it never run).
  `nr_ice_set_local_addresses` is Mozilla's, unchanged.
- `third_party/nICEr/src/stun/addrs-{bsd,netlink,netlink-wireless,win32}.{cpp,h}`, `nicer.gyp`, `moz.yaml`: as in the tag (not in
  this folder's patch). The bsd files are listed in nicer.gyp for every OS and are compiled on every leg as an empty unit (their body is
  under `#if defined(BSD) || defined(DARWIN)`, and nicer.gyp defines `BSD` and `DARWIN` only under its BSD and Mac conditions, `LINUX` and `WIN32` under theirs): the case
  of G25 does not arise, no function of ours served them alone.
- `nricectx.cpp`: the signature of Mozilla's `nr_socket_local_create` is renamed `nr_socket_local_create_Mozilla` (function wrap, G1,
  one line; the continuation line of the signature keeps its old alignment). `nricectx.h`: our include in a block of ours, the accessor
  `StealthPorts()` after `GetProxyConfig`, the member `host_ports_` after `proxy_config_` (construction is the default constructor of
  `StealthHostPorts`, so `NrIceCtx::NrIceCtx` and its includes are Mozilla's).
- `netwerk/base/nsIOService.cpp`: our include in a block of ours, and the IPv6 fact, one call at the top of `Init` in the parent (the
  parent-only and `MOZ_WEBRTC` conditions live in StealthIPv6Literal.cpp).
- `test/gtest_utils.h`: our include and the notice `StealthDeclareTestNetwork();` right after `NR_reg_init();` in `MtransportTest::SetUp` (where the base has it).
- Build lists: `dom/media/webrtc/transport/{moz.build,common.build,build/moz.build}`: one registration line each, after the closing
  bracket (`EXPORTS.transport += [...]`, `transport_lcppsrcs += [...]`, `TEST_DIRS += [...]`). The `common.build` line of network/doh is next to ours.
- The mDNS responder on the loopback. `ipc/StunAddrsRequestParent.cpp`: our include (registration); Mozilla's block that builds the list
  of the IPv4 addresses of the adapters is Mozilla's, and two one-line wraps decide what it feeds: the condition of
  `SendStunAddrs` is `if (StealthMdnsResponderWanted(!addrstring.empty()))` (true: the responder starts whatever list Mozilla built;
  Mozilla's operand is the argument) and the member of the wrapper object is `mAddrsString(StealthMdnsInterfaces(aAddrsString))`
  (`nr_stealth_mdns_interfaces()`, the loopback, in place of Mozilla's list). `mdns_service/src/lib.rs`: the join loop is Mozilla's, as
  it consumes `addrs`; `let stealth_if = addrs.first().copied();` before it and
  `stealth_interface::set_multicast_if(&socket, stealth_if);` after it (an anchor), so the two socket options keep their order, plus the
  registration `mod stealth_interface;` and `#[cfg(test)] mod stealth_tests;` after `extern crate log;`. The set of the interface and
  its warning are in stealth_interface.rs. Why: the responder joins the mDNS group on the loopback and speaks through it, not on the
  adapters of the list: the list is the declaration, whose address the OS does not own (a join on it fails, and the responder would never
  hear its own query); on the loopback the query and the answer make the same round trip through the responder's thread as on a real
  adapter. The responder speaks through the interface it joined on, or a query would leave on the default multicast route and never come
  back to its socket: on Linux a join on 127.0.0.1 hears nothing without it (captures/mdns-loopback/loopback-join of invisible_WebRTC).
  Tests: the gtest `StealthDeclaredNetwork.TheResponderStartsOnTheLoopbackWhateverListMozillaBuilt` (the two wraps, with the declared
  adapter as the negative control), the cargo test `mdns_service::stealth_tests::stealth_responder_on_the_loopback_hears_its_own_query`
  and the gtest `TheResponderOnTheLoopbackAnswersAQueryForANameItRegistered` (lib.rs; fails without `set_multicast_if_v4` on Linux, or
  without a join on the loopback).
- `dom/media/webrtc/transport/nr_socket_prsock.{h,cpp}` carries the R3 hooks (bind, own ports, loopback rewrite); the file belongs to
  network/proxy-udp, which has the other hooks in it, and the lines tagged `STEALTH-HOOK(fingerprint/webrtc/declared-network)` there call
  the functions below, which live in nr_stealth_network.{h,cpp} (G47). They are pure additions in nr_socket_prsock.cpp, none wraps a
  Mozilla function: `StealthOwnPeerToKernel` (`to = StealthOwnPeerToKernel(&my_addr_, to);`, first statement of `NrSocket::sendto`; the
  rewritten copy lives in a buffer of the calling thread until the next call) and `StealthOwnPeerFromKernel` (`StealthOwnPeerFromKernel(&my_addr_,
  from);` after Mozilla's conversion of the sender in `NrSocket::recvfrom`); the others take the socket's private fields as arguments
  (`my_addr_`, `stealth_own_port_`) and no friend: `StealthOwnPortsOfThisProcess`, `StealthBindAddress`, `StealthBindPortNotAvailable`,
  `StealthDeclaredAddressKept`, `StealthSocketAttachRefusedForTests`, `StealthSocketAttached`, `StealthOwnPortReleased`.

## Our own files

- `dom/media/webrtc/transport/mdns_service/src/stealth_tests.rs`: the cargo test of the responder on the loopback; lib.rs declares it with one line, `#[cfg(test)] mod stealth_tests;  // STEALTH-HOOK(...)`, after `extern crate log;`.
- `dom/media/webrtc/transport/mdns_service/src/stealth_interface.rs`: the multicast interface of the responder's socket, set after the join loop; lib.rs declares it with `mod stealth_interface;  // STEALTH-HOOK(...)`.

- `dom/media/webrtc/transport/nr_stealth_network.{h,cpp}` (the declaration, its parser, the default address and its guard, the host ports
  and `nr_socket_local_create`, the own-port rewrite, the IPv6 fact, the default family and the two wraps of the mDNS responder),
  `dom/media/webrtc/transport/third_party/nICEr/src/stun/nr_stealth_addrs.h` (the two C prototypes nICEr's own sources call, with
  nothing but struct names: no path out of nICEr's include directories, so `nicer.gyp` is Mozilla's),
  `dom/media/webrtc/transport/test/nr_stealth_test_network.h`,
  `dom/media/webrtc/transport/test/gtest/{moz.build,TestStealthDeclaredNetwork.cpp,TestStealthDeclaredNetworkBirth.cpp}`,
  `juggler/tests/ipv6_is_one_fact_of_the_declared_network.test.mjs`,
  `juggler/tests/the_host_network_is_read_nowhere_and_ports_are_the_connections.test.mjs`.
- `third_party/libwebrtc/api/location.h`: a header shim of the libwebrtc overrides, unrelated to the declaration (it lives here
  because the folder it was in is gone).
