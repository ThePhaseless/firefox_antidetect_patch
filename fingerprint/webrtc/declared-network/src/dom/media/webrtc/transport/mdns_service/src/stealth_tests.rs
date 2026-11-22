// The tests of ours for the responder of the declared network (hooks/fingerprint__webrtc__declared-network), apart from Mozilla's module `tests` in lib.rs.
use crate::Callback;
use crate::MDNSService;
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

// The responder started on the loopback, as the parent starts it (the declared address is not the host's, so the loopback is the
// interface given): its join of the group and the multicast interface it sets on its socket are what bring a query it sends
// back to its own socket, which answers it for a name it registered. Without them the query leaves on the default multicast
// route and the name is not resolved (on Linux a join on 127.0.0.1 hears nothing without the interface).
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
