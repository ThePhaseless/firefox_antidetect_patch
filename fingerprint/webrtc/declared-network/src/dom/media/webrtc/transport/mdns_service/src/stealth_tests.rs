/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// STEALTH-HOOK(fingerprint/webrtc/declared-network)
//
// The responder started on the loopback, as the parent starts it (the declared address is not the host's, so the loopback is the
// interface given): its join of the group and the multicast interface it sets on its socket (MDNSService::start) are what bring a
// query it sends back to its own socket, which answers it for a name it registered. Without them the query leaves on the default
// multicast route and the name is not resolved (on Linux a join on 127.0.0.1 hears nothing without the interface).

use super::*;
use std::ffi::c_void;
use std::os::raw::c_char;
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time;
use uuid::Uuid;

static OWN_NAME_RESOLVED: AtomicBool = AtomicBool::new(false);

unsafe extern "C" fn own_name_resolved(_: *const c_void, _: *const c_char, _: *const c_char) -> () {
    OWN_NAME_RESOLVED.store(true, Ordering::SeqCst);
}

unsafe extern "C" fn own_name_timedout(_: *const c_void, _: *const c_char) -> () {}

#[test]
fn stealth_responder_on_the_loopback_hears_its_own_query() {
    let mut service = MDNSService::new();
    let addr = "127.0.0.1".parse().unwrap();
    service.start(vec![addr]).unwrap();

    let hostname = Uuid::new_v4().as_hyphenated().to_string() + ".local";
    service.register_hostname(&hostname, "192.168.44.9");
    let callback = Callback {
        data: 0 as *const c_void,
        resolved: own_name_resolved,
        timedout: own_name_timedout,
    };
    service.query_hostname(callback, &hostname);

    let start = time::Instant::now();
    while !OWN_NAME_RESOLVED.load(Ordering::SeqCst) && start.elapsed() < time::Duration::from_secs(3) {
        thread::sleep(time::Duration::from_millis(10));
    }
    service.stop();
    assert!(
        OWN_NAME_RESOLVED.load(Ordering::SeqCst),
        "the query of the responder did not come back to its own socket"
    );
}

// The loop of MDNSService::start goes through stealth_note_first and the call after it takes the note: the list is handed back as
// it came, the first interface of it is the one set on the socket, the note is taken (a second socket gets none), and an empty
// list sets nothing.
#[test]
fn stealth_the_first_interface_of_the_list_is_the_one_set_after_the_loop() {
    let loopback: std::net::Ipv4Addr = "127.0.0.1".parse().unwrap();
    let list = vec![loopback, "10.255.255.254".parse().unwrap()];
    let given = stealth_interface::stealth_note_first(list.clone());
    assert_eq!(given, list);
    let mut joined = 0;
    for _ in given {
        joined += 1;
    }
    assert_eq!(joined, 2);

    let socket = std::net::UdpSocket::bind((loopback, 0)).unwrap();
    stealth_interface::set_multicast_if(&socket);
    assert_eq!(socket2::SockRef::from(&socket).multicast_if_v4().unwrap(), loopback);

    // Taken: another socket, with no list noted since, keeps the default interface.
    let other = std::net::UdpSocket::bind((loopback, 0)).unwrap();
    stealth_interface::set_multicast_if(&other);
    assert_ne!(socket2::SockRef::from(&other).multicast_if_v4().unwrap(), loopback);

    // An empty list notes nothing and sets nothing.
    assert!(stealth_interface::stealth_note_first(Vec::new()).is_empty());
    stealth_interface::set_multicast_if(&other);
    assert_ne!(socket2::SockRef::from(&other).multicast_if_v4().unwrap(), loopback);
}
