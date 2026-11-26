/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// Included by nr_socket_proxy_config.cpp at file scope, inside namespace mozilla, after the definition of
// NrSocketProxyConfig::Private, which only that file sees: the definition of the accessor the header gained (UdpProxy), the
// proxy the UDP of this PeerConnection leaves by, which StealthPcUdpProxyOf (netwerk/socket/StealthPcUdpProxy.h) filled in
// when the config was made. Not a header of its own: it needs the class above it, and is included once.

RefPtr<net::PcUdpProxy> NrSocketProxyConfig::UdpProxy() const {
  return mPrivate->mStealthUdpProxy;
}
