/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// STEALTH-HOOK(fingerprint/webrtc/declared-network)
//
// Windows only (gtest/moz.build): the port a declared host socket draws is its alone.
//
// A declared host UDP socket is bound to the wildcard address on a port of its connection (R3), and the datagrams of a connection to
// its own peers go to 127.0.0.1:port. On Windows a socket bound to a SPECIFIC address on the same port as a wildcard one is allowed
// (no option needed), and a datagram to 127.0.0.1:port goes to the specific one: another program's socket on 127.0.0.1 or on the
// address of the LAN would take the WebRTC datagrams of this browser (and the pair of two connections of the browser does not open
// until the checks time out). The retail socket binds the address of the interface on a port the kernel chose and cannot be taken
// over this way. Linux refuses the second bind (no SO_REUSEADDR on a UDP socket of ours or of NSPR), so this is a Windows rule: the
// socket is bound with SO_EXCLUSIVEADDRUSE.
//
//   * a port held on 127.0.0.1 by a socket of the test is refused by the bind of a declared host socket (R_ALREADY), and
//     nr_socket_local_create takes the next port of its connection;
//   * after the bind of a declared host socket, a bind of 127.0.0.1 on the same port is refused, with or without SO_REUSEADDR.
//
// The sockets are the real ones: NrSocket::create and nr_socket_local_create of a real NrIceCtx, on the socket thread.

#include "gtest/gtest.h"

#include <string.h>

#include <utility>

// nICEr is C++: its headers are not wrapped in extern "C".
// clang-format off
#include <csi_platform.h>
#include "nr_api.h"
#include "transport_addr.h"
#include "nr_socket.h"
#include "nr_socket_local.h"
#include "ice_ctx.h"
// clang-format on

#include "nr_socket_prsock.h"
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
#include "nss.h"
#include "prerror.h"
#include "prio.h"
#include "prnetdb.h"

namespace mozilla {
namespace {

const char kDeclared[] = "198.51.100.77";  // a documentation address: the host does not own it, as a declared one

// Runs aFn on the socket transport thread and returns when it has run.
template <typename F>
void OnSocketThread(F&& aFn) {
  nsresult rv;
  nsCOMPtr<nsISocketTransportService> sts = do_GetService(NS_SOCKETTRANSPORTSERVICE_CONTRACTID, &rv);
  ASSERT_TRUE(NS_SUCCEEDED(rv) && sts);
  nsCOMPtr<nsIEventTarget> target = do_QueryInterface(sts);
  ASSERT_TRUE(target);
  ASSERT_EQ(NS_OK, SyncRunnable::DispatchToThread(target, NS_NewRunnableFunction("StealthExclusivePort", std::forward<F>(aFn))));
}

nr_transport_addr UdpAddr(const char* aIp, uint16_t aPort) {
  nr_transport_addr a;
  EXPECT_EQ(0, nr_str_port_to_transport_addr(aIp, nullptr, aPort, IPPROTO_UDP, &a));
  return a;
}

uint16_t PortOfAddr(const nr_transport_addr& aAddr) {
  uint16_t port = 0;
  EXPECT_EQ(0, nr_transport_addr_get_port(&aAddr, &port));
  return port;
}

// The port after aPort in the dynamic range, as a connection hands them out: consecutive, 65535 wraps to 49152.
uint16_t PortAfter(uint16_t aPort) { return aPort == 65535 ? 49152 : aPort + 1; }

// An NrIceCtx made as the browser makes one, and closed at the end of the scope.
struct IceCtx {
  RefPtr<NrIceCtx> mCtx;

  explicit IceCtx(const char* aName) {
    if (!NSS_IsInitialized()) {
      NSS_NoDB_Init(nullptr);
    }
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

// A plain NSPR UDP socket (no option) bound to 127.0.0.1 on aPort (0: the system's choice). Null when the bind is refused.
PRFileDesc* PlainOnLoopback(uint16_t aPort, bool aReuseAddr = false) {
  PRFileDesc* s = PR_NewUDPSocket();
  if (!s) {
    return nullptr;
  }
  if (aReuseAddr) {
    PRSocketOptionData opt;
    opt.option = PR_SockOpt_Reuseaddr;
    opt.value.reuse_addr = PR_TRUE;
    EXPECT_EQ(PR_SUCCESS, PR_SetSocketOption(s, &opt));
  }
  PRNetAddr addr;
  PR_InitializeNetAddr(PR_IpAddrLoopback, aPort, &addr);
  if (PR_Bind(s, &addr) != PR_SUCCESS) {
    PR_Close(s);
    return nullptr;
  }
  return s;
}

uint16_t PortOf(PRFileDesc* aSocket) {
  PRNetAddr bound;
  EXPECT_EQ(PR_SUCCESS, PR_GetSockName(aSocket, &bound));
  return PR_ntohs(bound.inet.port);
}

}  // namespace

TEST(StealthExclusivePort, APortHeldOnTheLoopbackIsRefusedToADeclaredHostSocket)
{
  // The system gives a port; a plain socket holds it on 127.0.0.1, as another program of this machine would.
  PRFileDesc* holder = PlainOnLoopback(0);
  ASSERT_TRUE(holder);
  const uint16_t held = PortOf(holder);

  nr_transport_addr heldAddr = UdpAddr(kDeclared, held);
  RefPtr<NrSocket> refused = new NrSocket();
  int result = -1;
  OnSocketThread([&] { result = refused->create(&heldAddr); });
  if (result == 0) {
    OnSocketThread([&] { refused->close(); });
  }
  EXPECT_EQ(R_ALREADY, result) << "a declared host socket took a port that a socket of 127.0.0.1 holds: that socket would receive "
                                  "the datagrams the connection sends to its own peers";
  PR_Close(holder);
}

TEST(StealthExclusivePort, TheConnectionTakesTheNextPortWhenTheNextOneIsHeldOnTheLoopback)
{
  // A connection hands out consecutive ports from a base it drew. Its first socket tells the base; the next port is held on the
  // loopback by the test; the second socket must be born on the one after it. A port that someone else holds at that moment is
  // another try (the sockets of this machine are not the test's).
  bool done = false;
  for (int attempt = 0; attempt < 20 && !done; ++attempt) {
    IceCtx ice("stealth-exclusive-port");
    ASSERT_TRUE(static_cast<bool>(ice)) << "no ICE context";
    nr_transport_addr declared = UdpAddr(kDeclared, 0);
    nr_socket* first = nullptr;
    int firstResult = -1;
    OnSocketThread([&] { firstResult = nr_socket_local_create(ice.mCtx.get(), &declared, &first); });
    ASSERT_EQ(0, firstResult);
    nr_transport_addr firstBound;
    ASSERT_EQ(0, nr_socket_getaddr(first, &firstBound));
    const uint16_t firstPort = PortOfAddr(firstBound);
    OnSocketThread([&] {
      nr_socket_close(first);
      nr_socket_destroy(&first);
    });

    const uint16_t next = PortAfter(firstPort);
    PRFileDesc* holder = PlainOnLoopback(next);
    if (!holder) {
      continue;  // another program holds that port: another connection
    }
    nr_socket* second = nullptr;
    int secondResult = -1;
    OnSocketThread([&] { secondResult = nr_socket_local_create(ice.mCtx.get(), &declared, &second); });
    EXPECT_EQ(0, secondResult);
    if (secondResult == 0) {
      nr_transport_addr secondBound;
      EXPECT_EQ(0, nr_socket_getaddr(second, &secondBound));
      EXPECT_NE(next, PortOfAddr(secondBound)) << "the socket took the port that a socket of 127.0.0.1 holds";
      EXPECT_GE(PortOfAddr(secondBound), StealthHostPorts::kFirst);
      OnSocketThread([&] {
        nr_socket_close(second);
        nr_socket_destroy(&second);
      });
    }
    PR_Close(holder);
    done = true;
  }
  EXPECT_TRUE(done) << "in 20 connections the port after the first was always held by another program";
}

TEST(StealthExclusivePort, AfterTheBindOfADeclaredHostSocketNoOtherSocketCanBindThePort)
{
  // The port is the system's choice (a plain socket, then closed), taken by a declared host socket. A race with another program for
  // that port is another try.
  bool done = false;
  for (int attempt = 0; attempt < 20 && !done; ++attempt) {
    PRFileDesc* probe = PlainOnLoopback(0);
    ASSERT_TRUE(probe);
    const uint16_t port = PortOf(probe);
    PR_Close(probe);

    nr_transport_addr addr = UdpAddr(kDeclared, port);
    RefPtr<NrSocket> ours = new NrSocket();
    int result = -1;
    OnSocketThread([&] { result = ours->create(&addr); });
    if (result != 0) {
      continue;
    }
    done = true;

    PRFileDesc* plain = PlainOnLoopback(port);
    EXPECT_FALSE(plain) << "a socket of 127.0.0.1 bound the port of a declared host socket: it receives that socket's datagrams";
    if (plain) PR_Close(plain);
    // SO_REUSEADDR does not open the port: on Windows it is what lets a socket take over another's port.
    PRFileDesc* reusing = PlainOnLoopback(port, true);
    EXPECT_FALSE(reusing) << "a socket of 127.0.0.1 with SO_REUSEADDR bound the port of a declared host socket";
    if (reusing) PR_Close(reusing);
    OnSocketThread([&] { ours->close(); });
  }
  EXPECT_TRUE(done) << "no declared host socket was born in 20 tries";
}

}  // namespace mozilla
