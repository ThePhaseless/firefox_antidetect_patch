/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// The multicast interface of the responder's socket, set after the join of the group (MDNSService::start).
//
// The responder joins the group on the interfaces it is given and speaks through the first of them: a query it sends
// would otherwise leave on the default multicast route and never come back to its own socket, which is how it answers a
// name it registered (on Linux a join on 127.0.0.1 hears nothing without it). The first interface is read before the
// join loop, which takes the whole list, and set after it, so the two socket options keep their order.

use std::net::{Ipv4Addr, UdpSocket};

pub fn set_multicast_if(socket: &UdpSocket, interface: Option<Ipv4Addr>) {
    if let Some(addr) = interface {
        if let Err(err) = socket2::SockRef::from(socket).set_multicast_if_v4(&addr) {
            warn!("Could not send multicast through interface: {:?}: {}", addr, err);
        }
    }
}
