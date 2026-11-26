# network/proxy-udp

Category: other, spoof
Prefs: none
Test: gtest StealthPcProxyConfig.*, StealthTcpProxyRoad.*, StealthPcUdpProxyKinds.*, StealthUdpProxyBirth.*, StealthNrSocketBirth.* (dom/media/webrtc/transport/test/gtest), StealthSessionUdpProxy.* (netwerk/test/gtest/TestStealthSocksCredentials.cpp); TestStealthLookupLoadInfo.* (netwerk/test/gtest/TestStealthLookupLoadInfo.cpp, the socket process and the parent replayed in the order of sending, with the control: a constructor without its message has no load info), and TestStealthTRRContext.* (network/doh) for the message of the origin attributes; StealthHttp3Socks.*, StealthNsProxyInfoKinds.*, StealthSocksUdpLayer.* (netwerk/test/gtest/TestStealthHttp3Socks.cpp, the HTTP/3 truth tables and the layer of an HTTP/3 socket, each with its control); the node tests the_udp_of_a_socks5_proxy_is_a_flag_of_its_proxy_info, the_flag_of_the_coherent_udp_has_a_bit_of_its_own, a_peer_connection_of_a_torn_down_window_keeps_its_proxy_config, a_tcp_socket_of_a_peer_connection_is_refused_when_its_proxy_lookup_fails, the_ice_name_is_resolved_in_the_context_of_the_peer_connection (the last three assert the only entry; the second of them also asserts that the channel the swap drops is never opened and that both lookups swap through one function); modules/libpref/test/test_stealth_ice_prefs_locked.py (the only call of the lock); the e2e of invisible_playwright (srflx through the relay, proxy without UDP, TURN over TCP per context, two contexts, HTTP/3)

## What it does

Behind a SOCKS5 proxy the UDP of WebRTC (STUN, TURN) and of HTTP/3 leaves through the proxy's UDP relay, or does not leave,
and never goes out from the machine's own address. A browser with no proxy is a plain Firefox: nothing here changes it.

Only a SOCKS5 proxy the session measured coherent carries UDP: the core says it in the proxy it declares (`udp`: 'coherent', 'no' or
'unmeasured'), and the Juggler turns it into one flag of the nsIProxyInfo it builds, `nsIProxyInfo::CARRIES_COHERENT_UDP` (1 << 2;
`SessionRoute.udpFlagFor`: SOCKS5 and 'coherent' only). The flag is part of the proxy info's IPC clone, so it reaches the socket
process with the proxy. A "socks" proxy without it, SOCKS4 and HTTP are a router that drops: UDP goes nowhere, never direct, and
HTTP/3 falls back to h2 by itself.

The proxy is the one of the document, found by the same lookup Firefox uses for its TCP (ProxyConfigLookup, with the load
info of the page, so the filters of the Juggler answer for the context of the page). The load info is state of ours
(netwerk/ipc/StealthDocumentChannel): the caller sets it on the statement before `ProxyConfigLookup::Create` (`StealthSetLookupLoadInfo`,
"pending"), the first statement of `Create` takes it (`StealthEnterLookupLoadInfo`: pending becomes "active"), and it is read only by that
one call, so a lookup never sees the load info of another; no Mozilla signature carries it. In the parent process, after Mozilla made the
stand-in channel of the lookup, `StealthSwapLookupChannel` replaces it with the channel of the load info when the lookup has one; the channel
Mozilla made is a stand-in nobody opened and nobody opens. In the socket process `ProxyConfigLookupChild::Create` sends the load info in a
message of PSocketProcess, `StealthProxyLookupLoadInfo`, always (empty when empty), right before the constructor of PProxyConfigLookup; the parent parks
it in the slot of the socket process actor (`SocketProcessParent::RecvStealthProxyLookupLoadInfo`) and the first statement of
`RecvPProxyConfigLookupConstructor` takes it (`StealthTakeParkedLookupLoadInfo`). The messages of one protocol arrive in the order they were sent,
the take empties the slot and the next message overwrites it, so a constructor takes the message sent for it and a lookup made in the parent process
in between never reads it. The origin attributes of a DoH request travel the same way in a message of network/doh (`StealthProxyLookupOrigin`). `PcUdpProxy` (netwerk/socket/StealthPcUdpProxy)
keeps the answer for one PeerConnection: no proxy (direct), SOCKS5, or a proxy that carries no UDP (blocked). A lookup that
fails, or a document with no URI, is blocked: it never opens a road around the proxy.

The TCP sockets of a PeerConnection follow the same rule. At the end of `WebrtcTCPSocket::OnProxyAvailable` Mozilla opens the socket plain when the
lookup failed or gave a proxy of a type it does not know; `StealthTcpDirectRefused` (StealthIceResolverContext.cpp) closes it
instead: only the answer "no proxy" opens a plain socket. And a PeerConnection always has a proxy config: Mozilla's
`GetProxyConfig` returns none for a window that was torn down (a detached iframe, a closed popup), and a PeerConnection with no
config has plain sockets and a resolver in the default context. `StealthProxyConfigOf` keeps Mozilla's config when there is one
and otherwise builds it from the principal of the window; when that cannot be done the proxy is forced.

The UDP is decided where a socket is born. `NrSocket::create` (ICE sockets) and `nsUDPSocket::InitWithAddress` (HTTP/3,
`setSocksProxy`) push the SOCKS UDP layer (netwerk/socket/nsSOCKSUDPIOLayer) when the proxy is SOCKS5. The layer returns at
once: the association (resolve, connect, greeting, auth, UDP ASSOCIATE) is made afterwards on the socket thread, the first
datagrams are held (16 at most) and sent when it is ready, so a candidate is not late. The layer is pushed before the bind (an
AF_INET6 socket is made dual-stack, which a bound one can no longer be) and the socket takes its road, an association of the pool
included, only once it is born: after a bind that worked (`StealthBindAndBear` in `NrSocket::create`, `nsSOCKSUDPIOLayerSocketBorn`
after the `PR_Bind` of `nsUDPSocket`). A port the system refuses (in use, or a range Windows keeps for itself) is a socket that is
never born and takes nothing, so the socket born after a run of refused ports finds the ready associations. A proxy without UDP is a router that
drops: what is sent goes nowhere and nothing is received. Datagrams to loopback go direct in every state. In a content
process the UDP sockets of a PeerConnection are refused: they would go out direct.

The SOCKS5 connections of Necko tell the layer's pool the proxy (nsSOCKSIOLayer), so an association is warm when the first
socket asks for it. The sockets of the PeerConnections are made in the socket process, which opens no SOCKS5 connection of Necko's, so the
parent also tells it: one message, `PSocketProcess::StealthWarmSocksUdp` (host, port, user, pass), at most once per proxy and per socket
process and only for a proxy measured coherent, whose receiver (`SocketProcessChild::RecvStealthWarmSocksUdp`) calls the same
`nsSOCKSUDPIOLayerWarm`. Endpoint and credentials travel in this message only. TURN over TCP and the lookup of `ProxyConfigLookup` swap their channel through one function
(`StealthSwapChannelOfLoadInfo`, netwerk/ipc/StealthDocumentChannel), which only makes the channel of the load info
(`StealthNewChannelOfLoadInfo`) and replaces the old one in the caller's pointer.

HTTP/3 through SOCKS5: the h3 Alt-Svc is kept, the host name is resolved (QUIC needs the address) and the socket carries the
proxy; through a proxy that carries no UDP the handshake never completes and Firefox falls back to h2 by itself. neqo's own I/O
writes on the OS handle and would never reach the layer, so a SOCKS5 connection uses Firefox's own NSPR path
(`Http3Session::Init`, `mUseNSPRForIO`) and `nsUDPSocket::GetFileDescriptor` gives -1 for a socket that has the layer: nothing can
write on its handle by another road. An IPv6 destination goes through an IPv4 relay (the family that counts is the socket's; RFC 1928
allows a destination of any family), and a plain socket asked whether the layer failed answers no. An association that cannot
start (no socket transport service) is not a refusal of the proxy: it does not tell the pool, which would take the lock the caller
holds. The proxy of a PeerConnection is the context's, not the page address's: the lookup asks about a public https address with the
document's load info, so a page on the loopback, a `file:`, a `data:` or a document with no address follows the context's proxy.

## Hooks in Mozilla files

Every hook is one line with the marker, in a form of the contract; the explanations are here and next to our functions.

- `dom/media/webrtc/jsapi/PeerConnectionImpl.cpp`: Mozilla's initializer inside one call of `StealthProxyConfigOf` (network/doh, StealthIceResolverContext.h),
  `auto proxyConfig = StealthProxyConfigOf(mWindow.get(), mForceProxy, GetProxyConfig());` (a wrap of the expression: the window and the flag are the
  PeerConnection's private fields, passed in front of Mozilla's expression), and one include in a block of ours.
- `dom/media/webrtc/transport/ipc/WebrtcTCPSocket.{h,cpp}`: Mozilla's `OpenWithHttpProxy` and `AsyncResolve` are as Mozilla wrote them. Three anchors call into
  `ipc/StealthWebrtcTcpSocket.h` through its one friend (`StealthWebrtcTcpSocketAccess`, a `friend struct` line in the class). In `DoProxyConfigLookup`, after Mozilla's check of the
  channel it made, `if (StealthSwapTcpLookupChannel(this, channel, &rv)) return rv;` swaps it for the channel of the load info of the document (`StealthSwapChannelOfLoadInfo`,
  with the proxy flags the lookup is asked with, computed inside the friend): the proxy filters see the context of the page and not context 0, and the channel Mozilla made is never opened.
  At the end of `OnProxyAvailable`, after the dispatch on the proxy type, `if (StealthTcpSocketRefusesDirect(this, aResult, aProxyinfo)) return NS_OK;` (a failed lookup or an unknown
  type is refused, only "no proxy" opens the socket plain; a guard on top would have to copy the list of proxy types). In `OpenWithoutHttpProxy`, after Mozilla parsed the
  local address, `StealthTcpSocketBorn(this, &prAddr);` (the name context of the transport and the wildcard bind address; marker of fingerprint/webrtc/declared-network).
- `dom/media/webrtc/transport/nr_socket_proxy_config.{h,cpp}`: `UdpProxy()` and the member `mUdpProxy` (the last line of the `Private` block: the aggregate initialisation
  needs `mProxyConfig` first, an approved exception), and the lookup started where the `Private` is made: Mozilla's `new Private({aProxyConfig})` inside
  `net::StealthPcUdpProxyOf(aProxyConfig, <it>)` in the initialiser of `mPrivate` (a wrap of the expression, netwerk/socket; it starts the lookup on the new `Private`
  and hands it back, and the lookup has to start before the first socket of the gather asks for the proxy).
- `dom/media/webrtc/transport/nr_socket_prsock.{h,cpp}`: the NrSocket takes the proxy config of its PeerConnection (`NrSocket(config)` is an added constructor, Mozilla's default
  one is as Mozilla wrote it, and `friend struct StealthNrSocketAccess` gives our functions its fields); Mozilla's `new NrSocket()` inside `StealthNrSocketOf(config, new NrSocket())` in `CreateSocket` (parent and socket process, two wraps); `StealthUdpProxyAttachRefused(fd_, mProxyConfig)` in `create`
  right after the socket is opened (the layer is pushed before options and bind; a refused layer is R_INTERNAL: the socket must not exist); `StealthPRBind` for Mozilla's
  `PR_Bind` (a call wrap: the bind with its test seam, and the birth of the socket after a bind that worked); and `if (config) ABORT(R_REJECTED);` in the content-process
  branch of `CreateSocket` (a UDP socket of a PeerConnection made there would go out direct; the socket is made where the proxy is known and the layer can go on). The file also
  carries the hooks of fingerprint/webrtc/declared-network, one line each, calling `nr_stealth_network.{h,cpp}` with the private fields (`my_addr_`, `stealth_own_port_`): the
  bind address, the port that is not available, the declared address kept, the attach and its test seam, the release of the own port, and the own-peer rewrite of the destination
  in `sendto` and of the source in `recvfrom` (pure additions; the bodies of those two functions are Mozilla's).
- `netwerk/base/nsIUDPSocket.idl`: the forward declaration and `setSocksProxy`, one line each. `nsUDPSocket.{h,cpp}`: the member `mSocksProxy` and the three hooks of
  `InitWithAddress` and `GetFileDescriptor`, calls into `nsSOCKSUDPIOLayer.h` with the field of the socket (`StealthSocksUdpLayerFailed` after the open, `StealthSocksUdpBorn` after the bind,
  `StealthSocksUdpHasNoHandle` after the assertion of `GetFileDescriptor`); `nsUDPSocket::SetSocksProxy` is defined in `netwerk/socket/StealthPcUdpProxy.cpp`. `nsProxyInfo.h`: the declaration of `IsSOCKS5`, defined in
  the same file of ours. `nsIProxyInfo.idl`: the flag `CARRIES_COHERENT_UDP`, a value of ours in a slot of Mozilla's numbered space (an approved exception: the Juggler reads it
  by name; the node test the_flag_of_the_coherent_udp_has_a_bit_of_its_own fails if another constant takes the bit).
- `netwerk/protocol/http/{AlternateServices,DnsAndConnectSocket,Http3Session,HttpBaseChannel,HttpConnectionUDP}.cpp`: the HTTP/3 gates, each a call into `StealthHttp3Socks.h` with
  Mozilla's expression as an argument (`StealthProxyAllowsHttp3`, `StealthHttp3ThroughSocks5`, `StealthSocksResolvesHost`, `StealthUseNsprForSocksUdp`,
  `StealthSocksProxyIsHttp3Capable`) or an anchor in `InitCommon` after the TRR block (`StealthSocksProxyOfUdpSocketFailed`). `Http3ConnectUDPStream::SetSocksProxy` (not implemented: the
  CONNECT-UDP stream has its own proxy) is defined in `StealthHttp3Socks.cpp`; the file is Mozilla's again.
- `netwerk/socket/nsSOCKSIOLayer.cpp`: one call that warms the pool (`nsSOCKSUDPIOLayerWarm`: the design moves it to the top of the function, it stays where it is, because it is one
  line with a condition); the include block of ours; and the rewritten connect of the IPv6-literal gate (marker network/ipv6-literal, an approved exception).
- `netwerk/ipc/PSocketProcess.ipdl`, `SocketProcessChild.h`: the message `StealthWarmSocksUdp` and its receiver (defined in `netwerk/socket/nsSOCKSUDPIOLayer.cpp`);
  `SocketProcessChild.cpp` is Mozilla's again.
- The load info of the lookup (and, tagged network/doh, the origin attributes of a DoH request) goes with the lookup in two messages of ours, with no parameter in a Mozilla signature
  and no Mozilla line rewritten. `PSocketProcess.ipdl`: `StealthProxyLookupLoadInfo` (this folder) and `StealthProxyLookupOrigin` (network/doh), parent-bound, declared after
  `PProxyConfigLookup`; one message per folder, so that each marker names its owner. `ProxyConfigLookup.cpp`: `StealthEnterLookupLoadInfo();` as the first statement of `Create`
  and, after Mozilla's channel creation in `DoProxyResolve`, `if (StealthSwapLookupChannel(mURI, mProxyResolveFlags, channel, &rv)) return rv;`.
  `ProxyConfigLookupChild.cpp`: `StealthSendLookupLoadInfo(socketChild);` right before Mozilla's `SendPProxyConfigLookupConstructor` (the one sender of the constructor).
  `SocketProcessParent.{h,cpp}`: the declaration of `RecvStealthProxyLookupLoadInfo` (defined in `StealthDocumentChannel.cpp`, it parks the load info) and
  `StealthTakeParkedLookupLoadInfo(this);` as the first statement of `RecvPProxyConfigLookupConstructor`. `ProxyConfigLookup.h`, `ProxyConfigLookupParent.*` and
  `ProxyConfigLookupChild.h` are Mozilla's. The includes are in a block of ours.
- `toolkit/xre/nsAppRunner.cpp`: `StealthLockIcePrefs()` right after `mDirProvider.InitializeUserPrefs()` (an anchor: the lock has to see the user values) and an include in a block
  of ours; `toolkit/xre/moz.build` lists `StealthIcePrefs.cpp`.
- `moz.build` of netwerk/ipc, netwerk/socket, netwerk/protocol/http: our sources and headers, one line each after the closing bracket (`StealthDocumentChannel.{h,cpp}` in netwerk/ipc).

## Our own files

- `netwerk/socket/nsSOCKSUDPIOLayer.{h,cpp}` (the layer, its pool, and the three functions of the HTTP/3 socket), `netwerk/socket/StealthPcUdpProxy.{h,cpp}` (the proxy of a
  PeerConnection, `nsProxyInfo::IsSOCKS5`, `nsUDPSocket::SetSocksProxy`, the lookup of `NrSocketProxyConfig`), `netwerk/ipc/StealthDocumentChannel.{h,cpp}` (the channel of a
  document's load info), `dom/media/webrtc/transport/nr_stealth_proxy_udp.h` (the rule at the birth of a socket), `dom/media/webrtc/transport/ipc/StealthWebrtcTcpSocket.h` (the
  three functions of the TCP socket and their friend), `netwerk/protocol/http/StealthHttp3Socks.{h,cpp}` (HTTP/3 through SOCKS5), `toolkit/xre/StealthIcePrefs.{h,cpp}` (the lock of the two ICE prefs `network.process.enabled` and
  `media.peerconnection.mtransport_process`).
