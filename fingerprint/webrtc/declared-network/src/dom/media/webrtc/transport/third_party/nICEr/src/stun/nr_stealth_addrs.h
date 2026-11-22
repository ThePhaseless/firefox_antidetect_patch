/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* STEALTH-HOOK(fingerprint/webrtc/declared-network)
 *
 * The two functions of ours that nICEr's own sources call (addrs.cpp, ice_ctx.cpp), declared with nothing but the
 * struct names of nICEr: no <set>, no NSPR, no path out of nICEr's own include directories. The definitions are in
 * dom/media/webrtc/transport/nr_stealth_network.cpp (see nr_stealth_network.h for the declared network).
 *
 * nICEr is C++ and its headers are not wrapped in extern "C"; the definitions are, so the declarations are too.
 */

#ifndef nr_stealth_addrs_h__
#define nr_stealth_addrs_h__

#ifdef __cplusplus
extern "C" {
#endif

struct nr_local_addr_;
struct nr_ice_ctx_;

/* R1: the interface list, from STEALTHFOX_WEBRTC_NETWORK, with this process's temporary identifier. */
int nr_stealth_declared_addrs(struct nr_local_addr_* addrs, int maxaddrs, int* count);

/* R2: the default address of a family, with no route probe. Always answers (returns 1): *status is the status of
 * nr_ice_get_default_local_address and *addrp the default address on success.
 *
 * The default address of a family is the declared address of that family, found in the list the parent sent (`addrs`),
 * which is the declaration. No socket is connected and getsockname() is not read, so nothing of the host's routing
 * reaches the candidates. A family the declaration does not have has no default address (R_NOT_FOUND), as a machine
 * without a route in that family has none.
 *
 * The family of the page's server is a property of the real network path, which the declared machine hides: when the
 * context has a target for the lookup (nr_ice_set_target_for_default_local_address_lookup), `ip_version` is the target's
 * family, and a machine declared without IPv6 whose page was reached over IPv6 asks for the family it has (with no
 * default address of the target's family the gathering found no address at all, measured on the firefox-63 candidate,
 * Windows, direct: zero candidates). Without a target `ip_version` is the family that was asked for (NR_IPV4, NR_IPV6)
 * and stays: a request for IPv6 on a machine without IPv6 has no answer, never the IPv4 address. */
int nr_stealth_default_local_address_guard(struct nr_ice_ctx_* ctx, int ip_version, struct nr_local_addr_* addrs,
                                           int addr_ct, struct nr_local_addr_* addrp, int* status);

#ifdef __cplusplus
}  // extern "C"
#endif

#endif  // nr_stealth_addrs_h__
