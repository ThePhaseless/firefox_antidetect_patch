# network/ipv6-literal

Category: other
Prefs: none (the fact is the declared network's: network.dns.disableIPv6, set from the declaration by fingerprint/webrtc/declared-network)
Test: StealthDeclaredNetwork.* (netwerk/test/gtest/TestStealthIPv6Literal.cpp: AnIPv6LiteralFailsLikeAHostWithNoIPv6Route,
NothingIsBlockedWhileIPv6IsDeclared, AnAddressThatIsNotIPv6OrIPIsLeftAlone, TheConnectFailsWithTheRealErrorAndSendsNothing; the suite
name is the one already in the default gtest filter of the candidate); the node test
juggler/tests/ipv6_literal_fails_like_a_host_with_no_ipv6_route.test.mjs; the wrapper e2e
invisible_playwright/tests/test_ipv6_literal_connect_e2e.py::test_a_direct_ipv6_literal_is_refused_and_one_behind_socks_is_left_to_the_proxy

## What it does

With IPv6 declared off, a name never resolves to AAAA, but `nsHostResolver::FromIPLiteral` hands `http://[2001:db8::1]/` straight to the
socket and the host's own route would decide. Every direct TCP connection (pages, fetch, XHR, WebSocket, Happy Eyeballs, DoH, a
connection to an HTTP proxy) passes `nsSocketTransport::InitiateSocket`, and a SOCKS connection reaches its proxy in
`nsSOCKSSocketInfo::ConnectToProxy`: the transport wraps `PR_Connect` in `StealthConnect` and the SOCKS layer wraps its layer's connect
function pointer in `StealthHopConnect`, which chooses the function that is called. With the declaration, a routable IPv6
destination fails with `PR_NETWORK_UNREACHABLE_ERROR` (WSAENETUNREACH), the unspecified and multicast ones with
`PR_ADDRESS_NOT_AVAILABLE_ERROR`, and nothing is sent; both become `NS_ERROR_CONNECTION_REFUSED` as on Windows. `::1`, link-local and
IPv4-mapped addresses are left alone, and so is a destination behind a SOCKS proxy, which the proxy reaches, not this host.

## Hooks in Mozilla files

- `netwerk/base/nsSocketTransport2.cpp`:
  - the include of `StealthIPv6Literal.h`, in our block after Mozilla's includes (after the keepalive includes);
  - in `InitiateSocket`, the connect line: `status = StealthConnect(this, fd, &prAddr, NS_SOCKET_CONNECT_TIMEOUT);` is Mozilla's
    `PR_Connect(fd, &prAddr, NS_SOCKET_CONNECT_TIMEOUT)` statement with the called function replaced by ours and the transport, `this`,
    added in front: same statement, same assignment to `status`, Mozilla's arguments in place, no local, and `PR_GetError()` on the next
    line reads our error or `PR_Connect`'s own. The call cannot stay `PR_Connect` in the hook line: nothing may be sent when the
    destination is refused, and `fd` and `prAddr` are born in the middle of the function, so a guard at its head is impossible.
    The overload `StealthConnect(nsSocketTransport*, PRFileDesc*, const PRNetAddr*, PRIntervalTime)` reads the three fields of the
    transport through one friend of ours (`StealthSocketTransportAccess`, in `StealthIPv6Literal.cpp`) and calls the overload
    `StealthConnect(const NetAddr&, bool aProxyTransparent, const nsACString& aProxyHost, PRFileDesc*, const PRNetAddr*,
    PRIntervalTime)`, which takes the target the way the transport knows it: transparent and with a proxy host means `mNetAddr` is the
    destination of a SOCKS connection, which the proxy reaches (`kBehindSocksProxy`, never judged); else `kDirect`. It then calls the
    5-argument `StealthConnect`, which the gtests also use.
- `netwerk/base/nsSocketTransport2.h`: the one line `friend struct StealthSocketTransportAccess;` in the class, after
  `friend class nsSocketInputStream;`.
- Hooks of this feature in files another folder owns (a file has one owner): `netwerk/socket/nsSOCKSIOLayer.cpp` (network/proxy-udp:
  the connect to the proxy: `status = StealthHopConnect(this, fd->lower->methods->connect)(fd->lower, &prProxy, mTimeout);`, Mozilla's
  own expression, the layer's connect, inside our call with the socket info in front and Mozilla's arguments in place; the function
  it returns is chosen before anything is sent, takes the proxy's address from the call's own argument, and is `StealthConnect` with the
  target `kSocksProxyHop` on the layer below, which refuses the hop with the error set and nothing sent), `netwerk/base/moz.build` and `netwerk/test/gtest/moz.build` (network/socks). Their lines are tagged
  `STEALTH-HOOK(network/ipv6-literal)`.

## Our own files

- `netwerk/base/StealthIPv6Literal.{h,cpp}`, `netwerk/test/gtest/TestStealthIPv6Literal.cpp`,
  `juggler/tests/ipv6_literal_fails_like_a_host_with_no_ipv6_route.test.mjs` (it asserts the single entry: the one connect of
  `nsSocketTransport2.cpp` is the wrapper on the marked line, the friend is the one line of the class, and the choice of target is
  in `StealthIPv6Literal.cpp`).
