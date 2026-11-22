# network/doh

Category: build, other
Prefs: none (network.trr.* are Firefox's own; the build keeps network.trr.async_connInfo off and network.trr.exclude-etc-hosts false)
Test: TestStealthTRRContext.*, TestStealthSessionResolver.* and StealthIceResolverContext.* (netwerk/test/gtest and dom/media/webrtc/transport/test/gtest, in the default gtest filter of the candidate): they run the functions the hooks call, with fake channels
for the templates of the two channel classes (a failed lookup, a refused answer, a cancellation, a context with a proxy), a real channel for the context of a DoH request, and a real socket transport for the TLS over a tunnel; the node
tests of juggler/tests (the text pins of the hooks are gone: HOOKS.json declares the hooks, and these tests assert the only entry and the order against Mozilla's statements): dns_has_no_gate_of_ours, doh_never_goes_direct_when_its_proxy_is_lost,
doh_request_carries_the_context_of_its_lookup, proxy_info_leaves_name_resolution_to_the_browser,
trr_connection_info_is_not_cached_in_this_build, etc_hosts_exclusion_is_off, http_proxy_credentials_are_sent_preemptively_for_doh,
parental_controls_are_declared_off_where_the_os_is_read, doh_tunnel_is_not_shared_between_credentials,
doh_request_on_the_main_thread_fails_closed, no_channel_leaves_before_the_session_proxy_is_decided,
no_channel_leaves_before_the_network_observer_exists, no_ping_leaves_before_the_session_proxy_is_decided, no_lookup_asks_for_the_system_resolver, trr_follows_the_proxies_present,
warnings_reach_a_sink_that_is_not_gated, the_ice_name_is_resolved_in_the_context_of_the_peer_connection, the_ocsp_request_keeps_the_context_of_the_page,
the_profile_lock_looks_up_no_host_name, the_resolver_chooses_by_context, the_safebrowsing_completion_keeps_the_context_of_the_page, a_doh_request_answered_direct_is_ended,
a_channel_of_a_proxied_context_is_ended_when_its_proxy_lookup_fails

## What it does

Behind a proxy the names are resolved by Firefox's own DNS-over-HTTPS (TRR), and the DoH request leaves by the proxy of the
browser context whose lookup caused it. There is no DNS gate of ours: the resolver is upstream's, and the proxy info no longer
tells the proxy to resolve the host (the browser resolves the name and connects to the IP).

- The context. `StealthTRRContext` (netwerk/ipc) takes the user context id from the lookup's origin suffix and gives it to the load
  info of the TRR channel (`TRRLoadInfo` keeps the origin attributes, also in its clone) and to the stand-in channel of the proxy
  lookup, so the proxy filters (the Juggler's) answer for that context. The default context carries nothing: the browser's proxy
  answers it, as upstream. The cached connection info of the default server is not used for another context.
- Fail closed. A DoH request whose proxy lookup fails or cannot start ends with an error (`StealthTRRProxyFailure`) instead of
  failing over to DIRECT, which would send the name from the machine's own address. A cancellation keeps its own code.
- Fail closed on the main thread too. With no socket process, or after a proxy 401/407, the DoH request is sent from the main thread by a
  real `nsHttpChannel` (DNSUtils::CreateChannelHelper), whose own `OnProxyAvailable` would fail over to DIRECT. `StealthFailClosedOnProxyFailure`
  is true for a TRR channel, not cancelled, whose proxy lookup failed: it ends with `StealthTRRProxyFailure`. Other channels keep upstream's behaviour.
  The two channel classes reach the rule through templates of `StealthTRRContext.h` (`StealthTRRServiceProxyLookup` and
  `StealthTRRServiceOnProxyAnswer` for `TRRServiceChannel`, `StealthChannelProxyLookup` and `StealthChannelOnProxyAnswer` for `nsHttpChannel`),
  each read as a value of Mozilla's own call: the lookup of `ResolveProxy()` and the answer of `OnProxyAvailable` (`StealthChannelProxyLookup` returns at once for a lookup that went well, reading nothing). A failed lookup that must fail
  closed ends the channel and gives `NS_OK`, so the caller returns as it does after a lookup that went well. The anchor of the two answer hooks is
  `nsresult rv;`: above `mProxyRequest = nullptr` the reference to the finished lookup would survive `AsyncAbort`, and at the head of
  `TRRServiceChannel::OnProxyAvailable` the function still runs on the wrong thread (it is re-dispatched).
- The tunnel is isolated by credentials. The connection info of a DoH request carries the origin attributes of the context, so the tunnel
  (CONNECT through the proxy, which is authenticated) of one browser context is never reused by another context with other credentials.
- Parental controls are declared off, where the OS is read. The constructor of the Windows `nsIParentalControlsService` implementation
  returns before its first OS call (`StealthParentalControlsDeclared`, a header of toolkit/components/parentalcontrols): its
  initialisation list already holds the declared value (off). The Default (Linux) implementation reads no host and has its own `mEnabled(false)`;
  it is Mozilla's, as the Cocoa and Android ones are. Every reader (`nsHttpHandler`, the DoH heuristics, downloads,
  `CanonicalBrowsingContext`) goes through the service and sees the same value, so a host setting does not skip TRR
  (TRR_PARENTAL_CONTROL), add "Prefer: safe", or block downloads. The hosts file is not an exclusion either:
  `network.trr.exclude-etc-hosts` is false (guarded by a test).
- No lookup asks for the system resolver. Under TRR mode 3 a lookup that asks for the request mode "TRR disabled" is answered by the
  host's resolver anyway, so the request is resolved once, where every lookup enters the host resolver: `nsHostResolver::ResolveHost`
  and `DetachCallback` (the two functions that build the key of a record from the caller's flags) call `StealthApplySessionFlags`
  first (netwerk/dns/StealthSessionResolver: it puts the flags through `StealthFlagsFollowSession` from their address), which sets the two TRR mode bits by the proxy of the lookup's context. Only those bits:
  `RESOLVE_DISABLE_TRR` and every other flag stay. The one request that keeps its mode is the DoH request's own lookup of its
  server's name (resolving it through DoH would wait for itself). Without a proxy the mode is 0 and nothing changes. The services
  that stay on as in retail (`NetworkConnectivityService`, the captive portal detection and its tab, the OCSP channels) are
  Mozilla's, byte for byte. The test pins the central hook, that those files carry no change from the release, and an allowlist of
  every remaining TRR-disabling occurrence in non-test source, each with its verdict.
- The name of an ICE server is resolved in the context of its PeerConnection. `NrIceResolver` held default origin attributes, so the DoH
  request of the lookup of a `stun:` or `turn:` name left in the default user context. The resolver now holds the attributes of the
  PeerConnection (`SetOriginAttributes` / `GetOriginAttributes`, defined in our file, and the member after `vtbl_`), given by `StealthIceResolverSetContext`, an
  added line of `MediaTransportImplNicer::SetProxyConfig` after Mozilla's `if (!mIceCtx) return;` (a class local to that file, so it passes its resolver; the position is today's: at the
  head it would read the config on the closing road too), from the load info of its proxy config, and
  read by `NrIceResolver::resolve` through `StealthIceResolverLookupAttributes(this, &attrs);`, an anchor right after Mozilla's `OriginAttributes attrs;`, which stays with the
  `AsyncResolveNative` argument as Mozilla wrote it. `StealthIceResolverAttributes`
  (dom/media/webrtc/transport/StealthIceResolverContext) keeps the user context alone, which is what the proxy depends on.
  A TURN server given by name over TCP does not go through `NrIceResolver` (in the process that gathers, that path is set only in the parent
  process): `nsSocketTransport` resolves the name itself, so `WebrtcTCPSocket::OpenWithoutHttpProxy` calls `StealthTcpSocketBorn`
  (StealthIceResolverContext.cpp, declared in nr_stealth_network.h), whose `StealthTcpNameContext` gives the transport the same
  `StealthIceResolverAttributes` of the PeerConnection's load info, after `CreateTransport` and before `Bind`, where the transport is born.
- A request made for the TLS of a page keeps the context of the page. The OCSP request of a certificate is made with the system
  principal and Mozilla copies to it only the first party domain and the private browsing id, so it left in the default context:
  outside the proxy and the resolver of the page's context. `StealthKeepRequestContext` (netwerk/ipc/StealthTRRContext) adds the userContextId to Mozilla's copy: one added line after the copies, before
  Mozilla's `SetOriginAttributes(attrs)` (the page's attributes are `OCSPRequest::mOriginAttributes`, a field of a class local to nsNSSCallbacks.cpp, so the field is passed). The TLS layered over a tunnel (an HTTPS proxy,
  an HTTP/2 tunnel) was added to its socket with default attributes, so what it asks for had already lost the context:
  `StealthTransportContext(this, OriginAttributes())` gives it the attributes of the transport that carries it (`TLSTransportLayer` forwards
  `GetOriginAttributes` to it), as a direct connection has; Mozilla's default attributes are kept when there is none. The default context is unchanged, and the request belongs to no page, so no client route sees it.
- A channel of a context that has a proxy never goes out DIRECT because its proxy lookup failed. Mozilla fails over to DIRECT; the
  DoH channel was already ended instead (`StealthTRRFailClosed`), and `StealthProxyIsMandatory` (StealthSessionResolver.cpp) now
  says the same for every channel whose user context is in the declared list of contexts with a proxy. A context with no proxy
  keeps Mozilla's behaviour.
- The DoH prefs follow the proxies present. `juggler/TrrPrefs.js` derives them from the set of proxies the engine received (the
  browser-wide one plus every live context's): with at least one, mode 3, `network.trr.exclude-etc-hosts` false and
  `network.trr.excluded-domains` are set as user values; with none, exactly those three are cleared. The provider
  (`network.trr.uri`, `network.trr.bootstrapAddr`) is the core's: the engine neither writes nor clears it, and turning DoH on while
  `network.trr.uri` is empty throws before any write, so the proxy command is refused and the previous proxy restored.
  `TargetRegistry` recomputes them at `Browser.setBrowserProxy` / `setNoBrowserProxy` (before the held channels are released),
  `BrowserContext.setProxy` and the end of a context.
- The warnings that explain a hang reach stderr. The no-decision, failed-answer and hold-not-registered warnings go through `say()`
  (`juggler/Say.js`, owned by automation/juggler), which writes with `printStderr`: no pref, nothing a page reads, never throws, so
  an official build (`browser.dom.window.dump.enabled` false) shows them.
- Credentials of an http/https session proxy. `TRRServiceChannel` has no auth provider, so the 407 on the DoH CONNECT would never be
  answered: the channel is seeded with a preemptive `Proxy-Authorization` Basic header (UTF-8 bytes of user:pass) built from the
  nsIProxyInfo in `SessionRoute.js`. SOCKS keeps it empty: its credentials travel in the handshake.
- No channel before the proxy is decided (Juggler files, owned by automation/juggler). The proxy filter starts pending: channels asked
  before the first `Browser.setBrowserProxy` / `Browser.setNoBrowserProxy` wait unanswered (DoH lookups come through the same filter),
  and a proxy that cannot be expressed throws and leaves them pending. The NetworkObserver exists only from final-ui-startup, so
  `juggler/EarlyProxyHold.js` registers the hold filter at command-line-startup, once the pipe flag is known, and the NetworkObserver
  adopts it (one registration; without the flag nothing is registered). `TargetRegistry.roadOfSession` answers {decided, proxy}:
  the pingsender at exit does not start while the session is undecided (a null record means DIRECT).

## Hooks in Mozilla files

Every hook is one line with the marker, in a form of the contract; HOOKS.json lists them and names the test of each.

- `netwerk/dns/TRR.cpp`: an include of ours after Mozilla's; an anchor right after the check of the channel Mozilla makes,
  `if (StealthTRRApplyContext(mOriginSuffix, channel, &rv)) return rv;` (the channel is made in two places, so no expression wrap covers both; the
  suffix is the field `mOriginSuffix`, passed instead of a `friend`); and the pref operand of the cached-connection-info condition wrapped by
  `StealthTRRConnInfoUsable(mOriginSuffix, ...)` (one of Mozilla's lines rewritten). Our source is `netwerk/dns/StealthTRRRequest.{h,cpp}`, registered in `netwerk/dns/moz.build`.
- `netwerk/protocol/http/TRRServiceChannel.cpp`: an include; the lookup is `NS_SUCCEEDED(StealthTRRServiceProxyLookup(this, ResolveProxy()))` (one line rewritten),
  the answer an anchor after `nsresult rv;` in `OnProxyAvailable`, the connection info and the alternative service mapping take
  `StealthTRRConnectionAttributes(this, OriginAttributes())` in place of the default attributes (two lines rewritten); the proxy lookup of
  `ResolveProxy` passes `Nothing(), StealthTRRContextOf(this)` as two arguments added to `ProxyConfigLookup::Create` (one line rewritten, a pm-approved exception: no form adds arguments to a call; the context is that of its load info).
- `netwerk/protocol/http/nsHttpChannel.cpp`: an include; `NS_SUCCEEDED(StealthChannelProxyLookup(this, ResolveProxy()))` (one line rewritten) and an
  anchor `if (StealthChannelOnProxyAnswer(this, status, pi)) return NS_OK;` after `nsresult rv;` in `OnProxyAvailable`.
- `dom/media/webrtc/transport/nriceresolver.{h,cpp}`, `dom/media/webrtc/jsapi/MediaTransportHandler.cpp`: the resolver's origin attributes (the member after `vtbl_`, the two
  declarations of its accessors, defined in our file) and `StealthIceResolverSetContext(mDNSResolver, aProxyConfig);` after Mozilla's check of the ICE context in `SetProxyConfig`; the
  attributes of `resolve` are filled by `StealthIceResolverLookupAttributes(this, &attrs);` right after Mozilla's `OriginAttributes attrs;` (no Mozilla line rewritten);
  `dom/media/webrtc/transport/common.build` (fingerprint/webrtc/declared-network) lists our source.
- `dom/media/webrtc/transport/ipc/WebrtcTCPSocket.cpp` (owned by network/proxy-udp): the origin attributes of the PeerConnection on the
  transport of a TURN-over-TCP name are set inside `StealthTcpSocketBorn`, the one call at the bind (tagged
  fingerprint/webrtc/declared-network, which owns the bind address it also answers); its declaration is in
  `dom/media/webrtc/transport/nr_stealth_network.h`, which that file already includes.
- `security/manager/ssl/nsNSSCallbacks.cpp`: an include and `StealthKeepRequestContext(mOriginAttributes, attrs);` after Mozilla's two copies (an added line; Mozilla's `SetOriginAttributes(attrs)` is as it was).
- `netwerk/protocol/http/TLSTransportLayer.cpp`: an include, and the origin attributes argument of `AddToSocket` is
  `StealthTransportContext(this, OriginAttributes())` (one of Mozilla's lines rewritten: the wrong value is that argument).
- `toolkit/components/url-classifier/`: the Safe Browsing completion (gethash) of a page load is requested in the context of that
  page. `nsUrlClassifierDBService.cpp` opens a lookup-context scope from the page's principal in `Classify`, after the check of the permission, where it was (no test of `Classify` fixes an earlier place; helpers in
  netwerk/ipc/StealthTRRContext), keeps the context in a member after `mCallback`, and the completion callback answers it through a new `userContextId` attribute
  (`nsIUrlClassifierHashCompleter.idl`, after `completionV4`); `UrlClassifierHashCompleter.sys.mjs` hands a completion of a non-default context to
  the completer of that context (its channel gets the context through `stealthApplyContext(channel, this)`, an anchor after Mozilla's assignment of the channel's attributes: the request's `completer` is read in our function) (`StealthHashCompleterContext.sys.mjs`, registered in `moz.build` after the list of Mozilla's modules), whose channel carries that
  context: contexts never share a request, the default context is Mozilla's code; `tests/unit/xpcshell.toml` lists its test at the end.
- `toolkit/profile/moz.build`: one line, `DEFINES["MOZ_PROXY_BYPASS_PROTECTION"] = True`, after the list of sources. `nsProfileLock.cpp` is Mozilla's: the lookup of the machine's own
  host name in the Unix symlink lock (made at start-up, before any proxy is decided, through the system resolver) is already under that symbol, so the signature keeps 127.0.0.1.
  Only `nsProfileLock.cpp` reads the symbol in that directory (guarded by a test); the global option, which also changes a pref and the file picker, is not taken.
- `netwerk/dns/nsHostResolver.cpp`: an include and the two first statements `StealthApplySessionFlags(..., &flags);`; `netwerk/dns/moz.build`: our sources.
- `toolkit/components/parentalcontrols/nsParentalControlsServiceWin.cpp`: an include and the guard `if (StealthParentalControlsDeclared()) return;` as the first statement of the constructor
  (the Default, Cocoa and Android files are Mozilla's: those OSes are never the persona, or read no host).
- `modules/libpref/init/StaticPrefList.yaml` (the file is owned by fingerprint/webgpu/adapter-declaration), `network.trr.request_timeout_ms`: the value line carries the TRR-only timeout (30000); a proxied lookup is TRR_ONLY per request in global mode 0.
- `modules/libpref/init/StaticPrefList.yaml` (same file), `network.trr.exclude-etc-hosts`: the value line is false; the host's hosts file is never read, not even at start-up.
- Hooks of this feature in files another folder owns (a file has one owner): `netwerk/base/TRRLoadInfo.cpp`
  (automation/navigation), `netwerk/ipc/ProxyConfigLookup*.{h,cpp}`, `PSocketProcess.ipdl`, `SocketProcessParent.{h,cpp}`,
  `netwerk/ipc/moz.build` (network/proxy-udp: the lookup carries the origin attributes next to the load info),
  `netwerk/test/gtest/moz.build` (network/socks). Their lines are tagged `STEALTH-HOOK(network/doh)`. The Juggler files of the pending
  filter (NetworkObserver.js, TargetRegistry.js, Protocol.js, BrowserHandler.js, Juggler.js, SessionRoute.js) belong to automation/juggler.

## Our own files

- `netwerk/ipc/StealthTRRContext.{h,cpp}`, `toolkit/components/parentalcontrols/StealthParentalControls.h`,
  `netwerk/dns/StealthSessionResolver.{h,cpp}`, `netwerk/dns/StealthTRRRequest.{h,cpp}`, `netwerk/test/gtest/{TestStealthTRRContext,TestStealthSessionResolver}.cpp`,
  `dom/media/webrtc/transport/StealthIceResolverContext.{h,cpp}`, `dom/media/webrtc/transport/test/gtest/TestStealthIceResolverContext.cpp`, `juggler/EarlyProxyHold.js`, `juggler/TrrPrefs.js`, and the node tests above.
