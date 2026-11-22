# fingerprint/hardware/storage-quota

Category: spoof
Prefs: zoom.stealth.storage.quota_mb
Test: gtest:StealthQuotaEstimate.OriginScopeReportsThePrefInBytes, gtest:StealthQuotaEstimate.GroupScopeKeepsMozillasLimit, gtest:StealthQuotaEstimate.UnsetPrefChangesNeitherScope (the pure function); wrapper:tests/test_storage_estimate_quota_is_declared_e2e.py::test_storage_estimate_quota_is_the_declared_quota (the wiring)

## What it does

`navigator.storage.estimate().quota` reports the quota declared by the launcher (`zoom.stealth.storage.quota_mb`, in MB, when > 0) instead of the limit Mozilla computes from the host disk; with the pref unset (-1) Mozilla's limit is reported. Only the reported value changes: eviction keeps Mozilla's limits. The group scope of the same operation (parent process only, the ServiceWorker quota mitigation) keeps Mozilla's limit, as in retail.

## Hooks in Mozilla files

All in `dom/quota/OriginOperations.cpp`, own code in `dom/quota/StealthQuotaEstimate.h` (header only).

- registration: `#include "StealthQuotaEstimate.h"` in our block after Mozilla's includes.
- wrap-expression, `EstimateOp::GetResponse`: `estimateResponse.limit() = StealthEstimateLimit(mScope, mUsageAndLimit.second);` Mozilla's expression `mUsageAndLimit.second` is the argument; `mScope` (the private `EstimateOp::Scope`) is passed as an extra leading argument and the comparison with `Scope::Origin` is made in the template overload `StealthEstimateLimit(Scope, uint64_t)`, which calls `StealthEstimateLimit(uint64_t, bool aOriginScope)` (a scoped enum does not convert to bool, so the template is chosen). The bool overload stays: the gtest calls it.
- `dom/quota/test/gtest/moz.build`: `UNIFIED_SOURCES += ["TestStealthQuotaEstimate.cpp"]` after the closing `]` (registration, kept).

## Where the hook sits

Until 2026-10-29 the override sat inside `QuotaManager::GetUsageAndLimitForEstimate`
(dom/quota/ActorsParent.cpp), threaded through both of its returns. Firefox 159
rewrites that function, and it was the largest remaining conflict of the
157 -> 159 merge. `EstimateOp::GetResponse` (dom/quota/OriginOperations.cpp), where
the answer to the page is written, is identical in 157 and 159, so the hook is
there now, one call. From 159 the group scope of the same operation (parent
process only) reports the pinned quota too.

## Why the override exists

Comment that stood above the `stealthQuotaMb` / `stealthOverride` lines in ActorsParent.cpp, kept verbatim:

> Stealth: per-session storage quota override. When zoom.stealth.storage.quota_mb
> is > 0, navigator.storage.estimate().quota returns exactly that value (in MB).
> Default -1 = no override, vanilla Firefox behavior.
>
> [CORRECTED 2026-08-09] This used to say the override "masks the real disk
> size - one of the cross-session fingerprint signals - while staying in a
> realistic range". Both halves were wrong, and the second one measurably.
>
> There was nothing to mask. GetGroupLimitForLimit, a few lines above GetUsageAndLimitForEstimate in this file, caps
> the group limit at 10 GB in so many words - "cap the group limit to 10GB" -
> so every Firefox on a machine with a disk of 100 GiB or more reports
> exactly 10737418240 and the disk size never reaches the page. Firefox had
> already closed this.
>
> And the "realistic range" was 40 GiB to 3 TB across 13 sampled values, not
> one of which a real Firefox can return. Measured against stock 151: stock
> 10737418240, ours 429496729600. One line of JavaScript, and our answer was
> outside the set of possible answers.
>
> The declaration is 10 GiB now, which is what every real machine reports.
> The override stays because the field stays pinnable, and because on a
> genuinely small disk the real rule is disk/10.
