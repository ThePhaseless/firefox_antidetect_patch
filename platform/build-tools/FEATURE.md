# platform/build-tools

Category: build, port-fix
Prefs: none read directly
Test: scripts/ci/test_stealth_build_tools.py (AbsoluteObjectPathsTest, LongPathTest, JarFlatOutputTest, UnifiedNamesTest: the object path, the extended-length path, the jar.py line itself - the removal takes Mozilla's path, the open the hooked one - and the unified file names); scripts/ci/test_stealth_download_watchdog.py (the SDK download watchdog: cut file, timeout, unpicklable error, the call handed by the hook); both run by the `matrix` step of the plan job of release.yml (a full tree is materialized there; the line of the first is added to release.yml by the folder's commit)

## What it does

Four fixes of the build tools of Mozilla's tree, none of which reads or changes
what a page sees: the link rules list absolute object paths (mozmake 4.4.1 on
Win32 fails on relative paths over about 150 characters, libwebrtc's deeply
nested objects; an absolute path bypasses the bug and the linker accepts either,
on every platform and every build); the unified source files take the last 30
characters of the directory for their name instead of 20 (in libwebrtc,
goog_cc_scream_network_controller_gn and scream_network_controller_gn both
became "etwork_controller_gn" with 20 and collided; 30 gives two names), for
every build; the flat jar output opens its file (and only opens it: the removal of a previous file is Mozilla's, on the short path) with the Windows extended-length
prefix (the webcompat built-in add-ons have CSS file names long enough to
overflow MAX_PATH 260 from the objdir; abspath collapses the `..`, and the
prefix lifts the limit); and the SDK downloader of the cross build has a
per-file watchdog (a CDN edge dripped the Win11 SDK debuggers MSI for hours and
served a cut file five times; see `stealth_download_watchdog.py`).

## Hooks in Mozilla files

All wrap-expressions or value changes; the logic is in
`python/mozbuild/mozbuild/stealth_build_tools.py` and the watchdog.

- `python/mozbuild/mozbuild/backend/recursivemake.py`, `RecursiveMakeBackend._process_linked_libraries`: the `objs_ref` line is Mozilla's, with its generator element wrapped: `stealth_absolute_object_path(o, os.path.relpath(o, obj.objdir))`. The function returns its first argument (the absolute path); Mozilla's relative one is still evaluated and not used (it could raise only across drives, and objects are under the objdir). Import in a block of ours after Mozilla's.
- `python/mozbuild/mozbuild/frontend/data.py`, `UnifiedSources.__init__`: the number 20 is 30 on the two lines of Mozilla that carry it (the length test and the slice), a marker on each.
- `python/mozbuild/mozbuild/jar.py`, `OutputHelper_flat.getOutput`: one added line after Mozilla's removal of the previous output, `out = stealth_long_path(out)`, before the `open`. Mozilla's lines are the tag's: `os.remove` still receives the short path `ensureDirFor` returned, so a file that stayed before stays (over MAX_PATH the removal does nothing, as without the hook); only the `open` takes the extended-length path. Import in a block of ours.
- `third_party/python/vsdownload/vsdownload.py`, `_downloadPayload`: `stealth_urlretrieve(payload, destname, fileid, download=lambda: urllib.request.urlretrieve(payload["url"], destname))`. Mozilla's call is the lambda's body, so it is Mozilla's call that the alarm, the resume of a cut file and the conversion of an error that cannot cross the pool's pickling guard; `payload["url"]` is still read with the alarm armed. Import in a block of ours.

## Our own files

- `python/mozbuild/mozbuild/stealth_build_tools.py`
- `scripts/ci/test_stealth_build_tools.py`
- `scripts/ci/test_stealth_download_watchdog.py`
- `third_party/python/vsdownload/stealth_download_watchdog.py`
- `build/stealth_check_build_files.py`
- `build/stealth_check_sources.py`
