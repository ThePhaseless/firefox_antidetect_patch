/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// STEALTH-HOOK(fingerprint/webrtc/declared-network)
//
// Two places where nICEr's own code would read the host, or take the kernel's port, and does neither because of the
// declared network (nr_stealth_network.h). Both are asserted on the real functions of a real NrIceCtx, so they hold
// however the hooks that reach them are written.
//
//   R2  the default address of a family (nr_ice_set_local_addresses with ONLY_DEFAULT_ADDRS) is the declared address of
//       that family, and no socket is made to find it: the route probe of Mozilla (a UDP socket connected to a public
//       address, then getsockname) is never run. The context's socket factory counts what is asked of it; a control
//       asks it directly, so a count of zero is a count that works. The three ways nr_ice_get_default_local_address is
//       called are fixed: with a target (the family of the page's server, which a machine declared without IPv6 does
//       not have: it asks for the family it has) and the two without one (IPv4 and IPv6, each as asked: a request for
//       IPv6 on a machine without IPv6 has no answer, never the IPv4 address).
//   .local  the parent's mDNS responder, started on the loopback as the parent starts it (nr_stealth_mdns_interfaces), answers a
//       query for a name it registered: the join on the loopback and the multicast interface of its socket (mdns_service
//       lib.rs) are what bring the query back to its own socket.
//   R3  a host UDP socket of a declared address takes the next port of its connection: nr_socket_local_create, the
//       function of the context's socket factory, on an NrIceCtx. Consecutive from the base of that connection, a port
//       the system refuses is skipped, and a socket that is not a host socket of a declared address (the wildcard)
//       takes none. The test uses only what the function does, so it holds for the code before and after the hooks.

#include "gtest/gtest.h"

#include <string.h>

#include <atomic>
#include <string>
#include <vector>

// nICEr is C++: its headers are not wrapped in extern "C".
// clang-format off
#include <csi_platform.h>
#include "nr_api.h"
#include "registry.h"
#include "addrs.h"
#include "async_timer.h"
#include "transport_addr.h"
#include "local_addr.h"
#include "nr_socket.h"
#include "nr_socket_local.h"
#include "ice_ctx.h"
// clang-format on

#include "mdns_service/mdns_service.h"
#include "nr_stealth_network.h"
#include "nricectx.h"
#include "mozilla/RefPtr.h"
#include "mozilla/SyncRunnable.h"
#include "nsCOMPtr.h"
#include "nsIEventTarget.h"
#include "nsISocketTransportService.h"
#include "nsNetCID.h"
#include "nsServiceManagerUtils.h"
#include "nsThreadUtils.h"
#include "prerror.h"
#include "prinrval.h"
#include "prio.h"
#include "prnetdb.h"
#include "prthread.h"

namespace mozilla {
namespace {

const uint8_t kIid[8] = {0x1c, 0x5a, 0x37, 0x90, 0xe2, 0x4b, 0x08, 0xd1};

// Runs aFn on the socket transport thread and returns when it has run.
template <typename F>
void OnSocketThread(F&& aFn) {
  nsresult rv;
  nsCOMPtr<nsISocketTransportService> sts = do_GetService(NS_SOCKETTRANSPORTSERVICE_CONTRACTID, &rv);
  ASSERT_TRUE(NS_SUCCEEDED(rv) && sts);
  nsCOMPtr<nsIEventTarget> target = do_QueryInterface(sts);
  ASSERT_TRUE(target);
  ASSERT_EQ(NS_OK, SyncRunnable::DispatchToThread(target, NS_NewRunnableFunction("StealthDeclaredNetworkBirth", std::forward<F>(aFn))));
}

nr_transport_addr UdpAddr(const char* aIp, uint16_t aPort) {
  nr_transport_addr a;
  EXPECT_EQ(0, nr_str_port_to_transport_addr(aIp, nullptr, aPort, IPPROTO_UDP, &a));
  return a;
}

std::string IpOf(const nr_transport_addr& aAddr) {
  char ip[64];
  EXPECT_EQ(0, nr_transport_addr_get_addrstring(&aAddr, ip, sizeof(ip)));
  return ip;
}

uint16_t PortOfAddr(const nr_transport_addr& aAddr) {
  uint16_t port = 0;
  EXPECT_EQ(0, nr_transport_addr_get_port(&aAddr, &port));
  return port;
}

// An NrIceCtx made as the browser makes one, and closed at the end of the scope.
struct IceCtx {
  RefPtr<NrIceCtx> mCtx;

  explicit IceCtx(const char* aName) {
    NrIceCtx::InitializeGlobals(NrIceCtx::GlobalConfig());
    mCtx = NrIceCtx::Create(aName);
  }
  ~IceCtx() {
    if (mCtx) {
      mCtx->Destroy();
    }
  }
  explicit operator bool() const { return !!mCtx; }
};

// The socket factory of the context is replaced by one that counts the sockets asked of it and makes none.
int CountedCreateSocket(void* aObj, nr_transport_addr*, nr_socket**) {
  ++*static_cast<int*>(aObj);
  return R_INTERNAL;
}
int CountedDestroy(void**) { return 0; }
nr_socket_factory_vtbl sCountingFactory = {CountedCreateSocket, CountedDestroy};

const char kDual[] = "v4=192.168.1.23;v6=1;p6=2a01:e0a:1f2:3450::/64";
const char kV4Only[] = "v4=192.168.1.23;v6=0;p6=";
const char kV4[] = "192.168.1.23";
const char kV6[] = "2a01:e0a:1f2:3450:1c5a:3790:e24b:8d1";  // the prefix and kIid

struct DefaultAddresses {
  int mStatus = -1;
  int mSocketsAsked = -1;
  std::vector<std::string> mAddrs;
};

// What nr_ice_set_local_addresses leaves as the local addresses of a context that gathers the default ones only, for the
// declared machine aDecl; aTarget is the page's server (nullptr: none, as for a page that was not loaded over the network).
DefaultAddresses GatherTheDefaultAddresses(const char* aDecl, const char* aTarget) {
  DefaultAddresses out;
  IceCtx ice("stealth-default-addresses");
  if (!ice) {
    ADD_FAILURE() << "no ICE context";
    return out;
  }
  nr_ice_ctx* ctx = ice.mCtx->ctx();

  int counter = 0;
  nr_socket_factory* factory = nullptr;
  EXPECT_EQ(0, nr_socket_factory_create_int(&counter, &sCountingFactory, &factory));
  nr_ice_ctx_set_socket_factory(ctx, factory);
  // The control: a socket asked of the factory is counted, so a count of zero below is a count that works.
  nr_transport_addr any = UdpAddr("0.0.0.0", 0);
  nr_socket* none = nullptr;
  EXPECT_EQ(R_INTERNAL, nr_socket_factory_create_socket(ctx->socket_factory, &any, &none));
  EXPECT_EQ(1, counter);
  counter = 0;

  nr_ice_ctx_add_flags(ctx, NR_ICE_CTX_FLAGS_ONLY_DEFAULT_ADDRS);
  if (aTarget) {
    EXPECT_EQ(0, nr_ice_set_target_for_default_local_address_lookup(ctx, aTarget, 443));
  }
  nr_local_addr declared[4];
  memset(declared, 0, sizeof(declared));
  int count = 0;
  EXPECT_EQ(0, nr_stealth_parse_network(aDecl, kIid, declared, 4, &count));

  out.mStatus = nr_ice_set_local_addresses(ctx, declared, count);
  out.mSocketsAsked = counter;
  for (int i = 0; i < ctx->local_addr_ct; ++i) {
    out.mAddrs.push_back(IpOf(ctx->local_addrs[i].addr));
  }
  return out;
}

}  // namespace

TEST(StealthDeclaredNetwork, TheDefaultAddressesAreTheDeclaredOnesAndNoRouteIsProbed)
{
  struct Case {
    const char* mWhy;
    const char* mDecl;
    const char* mTarget;
    std::vector<std::string> mExpected;
  };
  const Case cases[] = {
      // With a target: the default address of the target's family, then the address of the other family on the same interface.
      {"a page over IPv4 on a dual-stack machine", kDual, "203.0.113.5", {kV4, kV6}},
      {"a page over IPv6 on a dual-stack machine", kDual, "2606:4700:4700::1111", {kV6, kV4}},
      {"a page over IPv4 on an IPv4-only machine", kV4Only, "203.0.113.5", {kV4}},
      // The machine hides the real path: the page was reached over IPv6, the declared machine has none and asks for the family it has.
      {"a page over IPv6 on an IPv4-only machine", kV4Only, "2606:4700:4700::1111", {kV4}},
      // Without a target: IPv4 and IPv6, each as asked.
      {"no target on a dual-stack machine", kDual, nullptr, {kV4, kV6}},
      {"no target on an IPv4-only machine: IPv6 asked, none answered, and never the IPv4 address twice", kV4Only, nullptr, {kV4}},
  };
  for (const Case& c : cases) {
    DefaultAddresses got = GatherTheDefaultAddresses(c.mDecl, c.mTarget);
    EXPECT_EQ(0, got.mStatus) << c.mWhy;
    EXPECT_EQ(0, got.mSocketsAsked) << c.mWhy << ": a socket was asked for, the route of the host was probed";
    EXPECT_EQ(c.mExpected, got.mAddrs) << c.mWhy;
  }
}

namespace {

// The port after aPort in the dynamic range, as a connection hands them out: consecutive, 65535 wraps to 49152.
uint16_t PortAfter(uint16_t aPort) { return aPort == 65535 ? 49152 : aPort + 1; }

// One connection, five host sockets: three of a declared address, a refused port between the second and the third, a wildcard
// socket (the kernel's) between the third and the fourth. aPorts gets the ports of the four declared ones.
struct PortRun {
  bool mBorn = false;
  uint16_t mPorts[4] = {0, 0, 0, 0};
  std::string mIps[4];
};

PortRun MakeTheSockets(const char* aDeclared) {
  PortRun run;
  IceCtx ice("stealth-host-ports");
  if (!ice) {
    ADD_FAILURE() << "no ICE context";
    return run;
  }
  nr_transport_addr declared = UdpAddr(aDeclared, 0);
  nr_transport_addr wildcard = UdpAddr("0.0.0.0", 0);
  nr_socket* socks[4] = {nullptr, nullptr, nullptr, nullptr};
  nr_socket* kernelChosen = nullptr;
  int results[4] = {-1, -1, -1, -1};
  int wildcardResult = -1;
  nr_transport_addr bound[4];
  OnSocketThread([&] {
    results[0] = nr_socket_local_create(ice.mCtx.get(), &declared, &socks[0]);
    results[1] = nr_socket_local_create(ice.mCtx.get(), &declared, &socks[1]);
    // The system refuses the next port (once): the socket takes the one after it, as the kernel would hand out another.
    StealthFailNextBindForTests(PR_NO_ACCESS_RIGHTS_ERROR);
    results[2] = nr_socket_local_create(ice.mCtx.get(), &declared, &socks[2]);
    StealthFailNextBindForTests(0);
    // Not a host socket of a declared address: it goes to the kernel and takes no port of the connection.
    wildcardResult = nr_socket_local_create(ice.mCtx.get(), &wildcard, &kernelChosen);
    results[3] = nr_socket_local_create(ice.mCtx.get(), &declared, &socks[3]);
    for (int i = 0; i < 4; ++i) {
      if (results[i] == 0) {
        EXPECT_EQ(0, nr_socket_getaddr(socks[i], &bound[i]));
      }
    }
  });
  run.mBorn = wildcardResult == 0;
  for (int i = 0; i < 4; ++i) {
    run.mBorn = run.mBorn && results[i] == 0;
    if (results[i] == 0) {
      run.mPorts[i] = PortOfAddr(bound[i]);
      run.mIps[i] = IpOf(bound[i]);
    }
  }
  OnSocketThread([&] {
    for (nr_socket*& s : socks) {
      if (s) {
        nr_socket_close(s);
        nr_socket_destroy(&s);
      }
    }
    if (kernelChosen) {
      nr_socket_close(kernelChosen);
      nr_socket_destroy(&kernelChosen);
    }
  });
  return run;
}

}  // namespace

TEST(StealthDeclaredNetwork, TheHostSocketsOfAConnectionTakeItsPortsInOrderAndSkipARefusedOne)
{
  const char* kDeclared = "198.51.100.77";  // a documentation address: the host does not own it, as a declared one

  // The ports are the connection's: from a random base, consecutive, a refused one skipped, none taken by a socket that is not
  // a declared host socket. A port that someone else holds at that moment is skipped too, as the kernel skips it, so the pattern
  // is looked for in connections of other bases when one of them met a held port (a connection that does not keep to its ports
  // never shows it).
  bool seen = false;
  for (int attempt = 0; attempt < 20 && !seen; ++attempt) {
    PortRun run = MakeTheSockets(kDeclared);
    ASSERT_TRUE(run.mBorn) << "a socket of the connection was not born";
    for (const std::string& ip : run.mIps) {
      EXPECT_EQ(kDeclared, ip) << "a host socket reports the declared address";
    }
    EXPECT_GE(run.mPorts[0], StealthHostPorts::kFirst);
    EXPECT_LE(run.mPorts[0], StealthHostPorts::kLast);
    seen = run.mPorts[1] == PortAfter(run.mPorts[0]) &&              // consecutive
           run.mPorts[2] == PortAfter(PortAfter(run.mPorts[1])) &&   // the refused port skipped
           run.mPorts[3] == PortAfter(run.mPorts[2]);                // the wildcard socket in between took none
  }
  EXPECT_TRUE(seen) << "no connection took its ports in order: consecutive from its base, a refused one skipped, none taken by "
                       "a socket that is not a declared host socket";
}

namespace {

// The answer of a query of the responder, written on its thread: 0 waiting, 1 resolved, 2 timed out.
struct MdnsAnswer {
  std::atomic<int> mState{0};
  std::string mAddress;
};

void MdnsResolved(void* aData, const char*, const char* aAddress) {
  MdnsAnswer* answer = static_cast<MdnsAnswer*>(aData);
  answer->mAddress = aAddress;
  answer->mState = 1;
}

void MdnsTimedOut(void* aData, const char*) { static_cast<MdnsAnswer*>(aData)->mState = 2; }

}  // namespace

TEST(StealthDeclaredNetwork, TheResponderOnTheLoopbackAnswersAQueryForANameItRegistered)
{
  // The parent starts the responder with nr_stealth_mdns_interfaces(): the declared address is not the host's, so a join on it
  // fails and the responder never hears its own query. On the loopback the query (sent through the interface the socket joined on)
  // comes back to the socket of the responder, which answers with the address the name was registered with.
  MDNSService* service = mdns_service_start(nr_stealth_mdns_interfaces());
  ASSERT_TRUE(service);
  mdns_service_register_hostname(service, "6f1c2a3e-8b4d-4e7a-9c15-2d3b4a5f6e70.local", "192.168.44.9");
  MdnsAnswer answer;
  mdns_service_query_hostname(service, &answer, MdnsResolved, MdnsTimedOut, "6f1c2a3e-8b4d-4e7a-9c15-2d3b4a5f6e70.local");
  for (int waited = 0; answer.mState == 0 && waited < 15000; waited += 20) {
    PR_Sleep(PR_MillisecondsToInterval(20));
  }
  mdns_service_stop(service);  // the responder's thread is done: no callback runs after this
  EXPECT_EQ(1, answer.mState.load()) << "the query of the responder did not come back to its own socket";
  EXPECT_EQ("192.168.44.9", answer.mAddress);
}

}  // namespace mozilla
