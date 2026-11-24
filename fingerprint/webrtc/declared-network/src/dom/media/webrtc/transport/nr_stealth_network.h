/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* STEALTH-HOOK(fingerprint/webrtc/declared-network)
 *
 * The network WebRTC gathers on is declared by the core, never read from the host.
 *
 * The declaration is the environment variable STEALTHFOX_WEBRTC_NETWORK, read where the interfaces are enumerated
 * (the parent: StunAddrsRequestParent::RecvGetStunAddrs -> nr_stun_get_addrs):
 *
 *     v4=<private IPv4>;v6=<0|1>;p6=<the /64 prefix of the exit, empty without IPv6>
 *
 * One adapter, as the modal Windows PC has: one private IPv4 address (RFC 1918), and when the machine has IPv6 the
 * temporary global IPv6 address of that adapter: the exit's /64 prefix and a temporary interface identifier drawn at
 * random (RFC 4941, as Windows does). v6=1 without a prefix is no IPv6, never a fallback. Under the default (no camera
 * or microphone permission) a page sees only the number of host names and their ranks; the addresses are
 * <uuid>.local names. Nothing of the host's adapters is read: the OS enumerators are not built.
 *
 * Without a declaration, or with one that does not parse, there is no interface: no host candidate, and an error in
 * the log. Never a fallback to the host.
 *
 * IPv6 is one fact for the whole browser. The same declaration decides network.dns.disableIPv6 in the parent
 * (StealthApplyDeclaredIPFamily, called once from nsIOService::Init): no IPv6 interface declared (v6=0, or v6=1 without
 * a prefix) means no AAAA lookup in any process, so a page is never loaded over an IPv6 address while ICE says there is
 * none. The answer is the parser's own (nr_stealth_declared_has_ipv6), never a second reading of the string.
 *
 * The declared address is the identity of this machine (R3, nr_socket_prsock.cpp): a host socket is bound to the
 * wildcard of its family on a port of the connection and reports the declared address with that port, and a datagram
 * between two of this browser's sockets travels on the kernel's loopback while each end sees the other's declared
 * address, as two sockets of one machine see its LAN address.
 */

#ifndef nr_stealth_network_h__
#define nr_stealth_network_h__

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

struct nr_local_addr_;
struct nr_transport_addr_;
struct nr_socket_;

/* Parses a declaration into at most `maxaddrs` entries; `iid` is the temporary interface identifier of the IPv6
 * address (8 bytes). 0 and *count = 1 or 2 on success; an error and *count = 0 for a missing or malformed one. */
int nr_stealth_parse_network(const char* decl, const uint8_t iid[8], struct nr_local_addr_* addrs, int maxaddrs,
                             int* count);

/* The IPv6 fact of a declaration, from the parser's own answer: 0 and *has = 1 when nr_stealth_parse_network accepts
 * `decl` and returns an IPv6 interface, *has = 0 when it accepts it and returns none; an error and *has = 0 for a
 * missing or malformed one. Quiet: it writes no log (the interface list is the one that reports a bad declaration). */
int nr_stealth_declared_has_ipv6(const char* decl, int* has);

/* R1: the interface list, from STEALTHFOX_WEBRTC_NETWORK, with this process's temporary identifier. */
int nr_stealth_declared_addrs(struct nr_local_addr_* addrs, int maxaddrs, int* count);

/* R2: the default address of `ip_version` is the first declared entry of that family among `addrs`; R_NOT_FOUND when
 * the declaration has none (the machine has no route in that family). No socket. */
int nr_stealth_default_local_address(int ip_version, struct nr_local_addr_* addrs, int addr_ct,
                                     struct nr_local_addr_* out);

/* The family of the default address to look for, given the family of the page's server: the target's family when the
 * list has an address of it, else the other one (a declared machine without IPv6 reaching a page over IPv6 asks for the
 * family it has); the target's family when the list has neither. */
int nr_stealth_default_family(int target_ip_version, struct nr_local_addr_* addrs, int addr_ct);

/* The interfaces the parent's mDNS responder joins the group on and speaks through: the loopback, "127.0.0.1;"
 * (lib.rs takes a ';'-separated list). The declared address is not the host's: a join on it fails. */
const char* nr_stealth_mdns_interfaces(void);

/* 1 when the ADDRESS of `addr` is the wildcard (0.0.0.0 or ::), whatever the port; 0 otherwise.
 * (nr_transport_addr_is_wildcard also calls port 0 a wildcard.) */
int nr_stealth_addr_is_wildcard_ip(const struct nr_transport_addr_* addr);

#ifdef __cplusplus
}  // extern "C"

#  include <set>

#  include "nscore.h"

// NSPR's address union. Not <prnetdb.h>: this header is included by nICEr's C++ files, which are compiled without the NSPR
// include path (run 43161344648: "prnetdb.h file not found" in ice_ctx.o and addrs.o); a file that uses the type includes it.
union PRNetAddr;
struct PRFileDesc;
class nsISocketTransport;
class nsIProxyInfo;

namespace mozilla {

/* Parent process, once, before any lookup: sets network.dns.disableIPv6 from the IPv6 fact of `aDecl` (the value of
 * STEALTHFOX_WEBRTC_NETWORK). As a DEFAULT value (never written to the profile) and the user value is cleared, so the
 * declaration is the only source. Returns true when it applied; false, and nothing touched, when there is no
 * declaration or it does not parse (a build run by hand keeps Firefox's behaviour). */
bool StealthApplyDeclaredIPFamily(const char* aDecl);

/* The same, for the declaration of this process's environment (STEALTHFOX_WEBRTC_NETWORK). */
bool StealthApplyDeclaredIPFamilyFromEnvironment();

/* R3: the host UDP ports of ONE connection (one ICE context), as Windows hands them out: consecutive in the order the
 * sockets are made (the IPv4 host N, the IPv6 host N+1), from a base drawn at random in the dynamic range 49152-65535,
 * anew for each connection. Not the kernel's ports and not derived from the seed: two visits of one seed must not
 * share them (retail: captures/retail/firefox-159.0-win/two-pc-port-sequence of invisible_WebRTC, each connection its
 * own pair, unrelated to the last). A busy port is skipped, as the kernel skips it; after 65535 it wraps to 49152. */
class StealthHostPorts final {
 public:
  static constexpr uint32_t kFirst = 49152;
  static constexpr uint32_t kLast = 65535;

  /* A new connection: the base is drawn here, from the process's generator (mozilla::RandomUint64OrDie), when the owner
   * (NrIceCtx, a member) is constructed. */
  StealthHostPorts();

  /* `aRandom`: a random number from the caller's generator (mozilla::RandomUint64). */
  explicit StealthHostPorts(uint64_t aRandom)
      : mNext(kFirst + static_cast<uint32_t>(aRandom % (kLast - kFirst + 1))) {}

  uint16_t Next() {
    uint32_t port = mNext;
    mNext = port == kLast ? kFirst : port + 1;
    return static_cast<uint16_t>(port);
  }

  /* The first port from here on for which `aTry(port)` is true (the bind worked, or any other reason to keep it), or 0 when
   * none of the 16384 is. The kernel hands out only ports it can bind: Windows keeps ranges of the dynamic range
   * (Hyper-V, WSL, Docker: about one port in ten on a developer PC) for the system, and a bind to one fails with
   * "access denied"; a port another socket holds fails as "in use". Either way the next port is tried, as the kernel
   * would have given another. */
  template <typename F>
  uint16_t NextAvailable(F aTry) {
    for (uint32_t n = 0; n <= kLast - kFirst; ++n) {
      uint16_t port = Next();
      if (aTry(port)) return port;
    }
    return 0;
  }

 private:
  uint32_t mNext;
};

/* R3: the ports this process's declared host sockets are bound to, per family. A datagram TO our declared address and
 * one of these ports goes to the loopback of the family (the declared address is not the host's; the kernel would
 * route it away); one FROM the loopback and one of these ports is reported as coming from our declared address.
 * Nothing else is touched: a server on localhost (a page's STUN server on 127.0.0.1) keeps its address. */
class StealthOwnPorts final {
 public:
  void Add(int aIpVersion, uint16_t aPort) { mPorts.insert(Key(aIpVersion, aPort)); }
  void Remove(int aIpVersion, uint16_t aPort) { mPorts.erase(Key(aIpVersion, aPort)); }
  bool Has(int aIpVersion, uint16_t aPort) const { return mPorts.count(Key(aIpVersion, aPort)) != 0; }

 private:
  static uint32_t Key(int aIpVersion, uint16_t aPort) {
    return (static_cast<uint32_t>(aIpVersion) << 16) | aPort;
  }
  std::set<uint32_t> mPorts;
};

/* R3 for the TCP socket that talks to a TURN or STUN server (WebrtcTCPSocket): the connection's declared address is not an
 * address of this host, so it can only give the FAMILY, never the bind address. The socket binds the wildcard of that
 * family on port 0, so the system hands out a free port and a range it keeps for itself (Windows reserves some of the
 * dynamic range for Hyper-V, WSL, Docker, and refuses a bind to them) can never refuse it. The local port of such a
 * socket is nowhere a page can read: a relay candidate carries the server's mapped address, not the local one, and the TCP
 * host candidate that is announced is the active one, which declares port 9. False when `aDeclaredAddress` does not
 * parse as an address. `aNicerPort` is the port nICEr proposed, only logged (WebrtcTCPSocket log module). */
bool StealthTcpBindAddress(const char* aDeclaredAddress, uint16_t aNicerPort, union PRNetAddr* aOut);

/* R3, NrSocket (nr_socket_prsock.cpp): the hooks of NrSocket::create, ::sendto, ::recvfrom and ::close call these. The private state of the socket (its address, the port registered as one of ours) is
 * passed as those fields, never by a friend of ours: the hook line names the field. */

/* The declared host sockets of this process: the ports their datagrams to our own declared address must reach on the
 * loopback. Every NrSocket lives on the socket transport thread, so no lock. A function-local static, as it was inline. */
StealthOwnPorts& StealthOwnPortsOfThisProcess();

/* NrSocket::create, right after Mozilla's nr_transport_addr_to_praddr(addr, &naddr): the address of a candidate is declared,
 * not the host's, so unless it is the wildcard or the loopback the kernel socket is bound to the wildcard of the candidate's
 * family on the candidate's port: `aNaddr` becomes that. True on failure (the port cannot be read or the address set): the
 * caller aborts with R_INTERNAL. */
bool StealthBindAddress(const struct nr_transport_addr_* aAddr, union PRNetAddr* aNaddr);

/* NrSocket::create, first line inside the failed bind: the port is not available (another socket holds it, or the system
 * keeps it: Windows reserves ranges of the dynamic range and answers "access denied"), by the NSPR error of the bind. The
 * caller aborts with R_ALREADY and nr_socket_local_create takes the next port, as the kernel would. */
bool StealthBindPortNotAvailable();

/* NrSocket::create, around Mozilla's nr_praddr_to_transport_addr(..., &my_addr_, ...) of the wildcard-port block: `aMozillaResult`
 * is its answer, returned unchanged when it failed or when the candidate is the wildcard (the kernel's address is then the
 * socket's). For a declared address the kernel's port is taken, and the socket reports the declared address with it: `aMyAddr`
 * (the socket's my_addr_) is the declared address `aAddr` with the port it now holds. */
int StealthDeclaredAddressKept(struct nr_transport_addr_* aMyAddr, const struct nr_transport_addr_* aAddr, int aMozillaResult);

/* NrSocket::create, before Mozilla's AttachSocket: tests only, the next UDP create (once) finds the socket transport service
 * refusing the socket (StealthFailNextSocketAttachForTests). True = abort with R_INTERNAL. */
bool StealthSocketAttachRefusedForTests(const struct nr_transport_addr_* aAddr);

/* NrSocket::create, around Mozilla's `stservice->AttachSocket(fd_, this)`: `aMozillaResult` is its answer, returned unchanged. A
 * declared UDP host socket is one of ours once the socket transport service took it, as the LAST step of create: when the answer
 * succeeded and `aAddr` is UDP and the socket's address `aMyAddr` is neither wildcard nor loopback and has a port, the port is
 * registered (StealthOwnPortsOfThisProcess) and kept in `aOwnPort` (the socket's stealth_own_port_). A create that aborts before
 * leaves nothing in the set. */
nsresult StealthSocketAttached(const struct nr_transport_addr_* aMyAddr, uint16_t* aOwnPort,
                               const struct nr_transport_addr_* aAddr, nsresult aMozillaResult);

/* NrSocket::sendto, first statement: `to = StealthOwnPeerToKernel(&my_addr_, to);`. The destination as the kernel needs it: to
 * another socket of this browser at our declared address (`aMyAddr` is the socket's my_addr_) it is the loopback, same port, in a
 * buffer of this thread valid until the next call; else `aTo` itself. */
const struct nr_transport_addr_* StealthOwnPeerToKernel(const struct nr_transport_addr_* aMyAddr,
                                                        const struct nr_transport_addr_* aTo);

/* NrSocket::recvfrom, after Mozilla's conversion of the sender into `aFrom`: from the loopback and one of our ports, the peer is
 * our declared address. */
void StealthOwnPeerFromKernel(const struct nr_transport_addr_* aMyAddr, struct nr_transport_addr_* aFrom);

/* NrSocket::close: the port registered by StealthSocketAttached is removed and `aOwnPort` is zeroed. */
void StealthOwnPortReleased(const struct nr_transport_addr_* aMyAddr, uint16_t* aOwnPort);

namespace net {
class WebrtcProxyConfig;
}

/* network/doh (defined in StealthIceResolverContext.cpp): the transport of a TCP socket of a PeerConnection looks its
 * host name up in the browser context of that PeerConnection, as NrIceResolver does for the names of the UDP candidates.
 * A TURN server given by name over TCP does not go through NrIceResolver in the process that gathers: the name reaches
 * the socket transport, whose default attributes are those of the default context. Called right after the transport is
 * created and before it is bound (a transport refuses its attributes once its socket exists). `aConfig` is the proxy
 * config of the socket (it carries the load info of the PeerConnection), null when it has none: nothing is done. */
void StealthTcpNameContext(nsISocketTransport* aTransport, const net::WebrtcProxyConfig* aConfig);

/* network/proxy-udp (defined in StealthIceResolverContext.cpp): what WebrtcTCPSocket::OnProxyAvailable does when it has neither an HTTP proxy
 * nor a SOCKS or direct proxy info to open with and would open the socket plain (DIRECT). A socket of a PeerConnection whose context has
 * a proxy never goes out plain because a lookup failed or answered something it does not know: true = REFUSE (close the socket). The only
 * answer that opens it plain is "no proxy" (the lookup succeeded and gave no info): that context has none. A socket with no proxy config
 * is not a PeerConnection's: left as upstream has it. This is the decision UDP takes in PcUdpProxy::KindFor, for TCP. */
bool StealthTcpDirectRefused(bool aHasProxyConfig, bool aLookupFailed, nsIProxyInfo* aInfo);

/* The two things a plain TCP socket of a PeerConnection is given before it is bound, in one call: the context of its name lookup
 * (StealthTcpNameContext) and the family of its bind address (StealthTcpBindAddress). False when the declared address does not parse. */
bool StealthTcpSocketBorn(nsISocketTransport* aTransport, const net::WebrtcProxyConfig* aConfig, const char* aDeclaredAddress,
                          uint16_t aNicerPort, union PRNetAddr* aOut);

/* Tests only: the next NrSocket::create (once) finds the socket transport service refusing the socket, at the step just before a declared
 * host socket is registered as one of ours (R3). A create that fails there must leave nothing in the set of our ports. */
void StealthFailNextSocketAttachForTests(bool aFail);
bool StealthTakeFailNextSocketAttachForTests();

/* The bind of NrSocket::create (R3: the wildcard of the candidate's family, on the candidate's port): PR_Bind, true when it bound. On Windows
 * a UDP socket bound to a port that is not the kernel's choice is bound with SO_EXCLUSIVEADDRUSE: no other socket holds that port on any address,
 * and none can take it afterwards (a port another socket holds is the caller's next port). Tests
 * only: StealthFailNextBindForTests(aError) makes the next one (once) fail with the NSPR error aError (e.g. PR_NO_ACCESS_RIGHTS_ERROR, which
 * Windows answers for the ranges of the dynamic range it reserves and Linux for a privileged port), so the mapping of that answer is
 * asserted on every machine, not only on one that happens to refuse a port. 0 = none. */
bool StealthBind(struct PRFileDesc* aFd, const union PRNetAddr* aAddr);
void StealthFailNextBindForTests(int32_t aError);

}  // namespace mozilla

/* The body of Mozilla's nr_socket_local_create (nricectx.cpp), whose name it takes. nr_socket_local_create itself is ours
 * (nr_stealth_network.cpp): the nICEr socket factory of every NrIceCtx calls it (ctx_socket_factory_vtbl). A host UDP
 * socket of a declared address takes the next port of its connection (R3; NrIceCtx::StealthPorts): the base address is
 * copied with that port and the body of Mozilla's function runs on it, whole and unchanged, once per try; a busy port
 * (R_ALREADY from NrSocket::create) is skipped as the kernel skips it, any other answer is the answer. 16384 busy ports
 * are R_ALREADY, a copy that fails is R_INTERNAL. A socket with no connection (`obj` null: stunserver, tests), a TCP one,
 * and one on the wildcard or the loopback go straight to the body of Mozilla's function with the address they were given.
 * C++ linkage, as nr_socket_local.h declares the wrapper. */
int nr_socket_local_create_Mozilla(void* obj, struct nr_transport_addr_* addr, struct nr_socket_** sockp);

/* For a socket whose identity is `self` (the declared address and its bound port): the peer of a datagram as the
 * kernel needs it (to) and as ICE must see it (from). Each returns 1 when it rewrote `addr`, 0 when it left it. */
int nr_stealth_own_peer_to_kernel(const struct nr_transport_addr_* self, const mozilla::StealthOwnPorts& own,
                                  struct nr_transport_addr_* addr);
int nr_stealth_own_peer_from_kernel(const struct nr_transport_addr_* self, const mozilla::StealthOwnPorts& own,
                                    struct nr_transport_addr_* addr);

#endif  // __cplusplus

#endif  // nr_stealth_network_h__
