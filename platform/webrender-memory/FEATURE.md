# platform/webrender-memory

Category: other
Prefs: none read directly
Test: the wrapper e2e `tests/test_web_fonts_of_closed_contexts_e2e.py::test_the_web_fonts_of_closed_contexts_leave_the_shared_archive` (10/20/40 contexts closed, invisible_playwright#445, from firefox-61: it fails when the notice in `register_window` or the one in `process_scene_builder_result` is missing); and the Rust unit tests of our module, `cargo test -p webrender --lib stealth_shared_fonts` (needs libclang for mozangle): `the_fonts_of_a_namespace_leave_the_shared_resources_when_its_window_is_gone` (fails when the notice in `process_scene_builder_result` is removed), `the_fonts_of_another_namespace_stay`, `a_namespace_takes_its_fonts_out_of_the_shared_resources`, `a_font_two_namespaces_have_stays_until_the_last_one_is_cleared` and `another_namespace_is_not_touched` (the last three fail when `clear_shared_fonts` stops removing).

## What it does

WebRender clears what a window left in the resources every window of its pool shares when the window's namespace is cleared. A window's `ResourceCache` takes the namespace's fonts out of the shared font resources, but a window that left first (`ApiMsg::UnregisterWindow` reaches the render backend on the direct channel, `SceneBuilderResult::ClearNamespace` on the low-priority scene builder queue) took its resource cache with it: nobody would ever take its font templates, font instances and key mappings out, and they stayed in the pool's shared resources for as long as the pool lives (a web font of a closed page is up to a few MB, kept once per distinct font; the glyph cache lives in the window's own `ResourceCache` and goes with it). Measured on firefox-60: 10 / 20 / 40 contexts with a font of their own kept 10.4 / 19.8 / 40.7 MB.

The render backend remembers the shared font resources when a window is registered (`RememberedFonts`, a field of `RenderBackend`; every window of a backend is handed the same instance, the one of the pool: `renderer::init` takes `options.shared_fonts` and `wr_render_backend_pool_new` clones one `SharedFontResources` into every member and every `RenderApi`). For a `ClearNamespace(backend_id, id)` with no window registered under `backend_id` it clears them itself, with the five steps of `ResourceCache::clear_namespace` that work on the shared resources, in the same order (`clear_shared_fonts`). A registered window is left to Mozilla's own arm and `ResourceCache::clear_namespace`, which are Mozilla's text again.

## Our files

- `gfx/wr/webrender/src/render_backend/stealth_shared_fonts.rs`: a child module of `render_backend` (Rust finds it next to `render_backend.rs`), so that it reads the backend's private `windows` and `stealth_fonts` and calls the private `process_scene_builder_result` in its tests. It holds `RememberedFonts`, `remember_fonts`, `clear_when_window_left`, `clear_shared_fonts` (and `ClearedFonts`, what it took out, which only the tests read), and the five tests above. It depends on these `pub` methods of Mozilla's: `FontTemplateMap::{clear_namespace, delete_fonts}`, `FontInstanceMap::{clear_namespace, delete_font_instances}`, `FontInstanceKeyMap::clear_namespace`, `FontKeyMap::clear_namespace` (gfx/wr/wr_glyph_rasterizer/src/rasterizer.rs): if Mozilla changes the steps `ResourceCache::clear_namespace` takes on the shared maps, `clear_shared_fonts` follows.

## Hooks in Mozilla files

All in `gfx/wr/webrender/src/render_backend.rs`:

- `mod stealth_shared_fonts;` (registration, after the last `use`, in a block of ours): registers the module.
- `stealth_fonts: stealth_shared_fonts::RememberedFonts,` in `struct RenderBackend` (member, after `dl_stores`) and `stealth_fonts: stealth_shared_fonts::RememberedFonts::empty(),` in the struct literal of `RenderBackend::new` (the field's installation, after `dl_stores`): the state of our logic is a field of the structure (a thread-local would rely on an assumption about how Mozilla uses the backend).
- `stealth_shared_fonts::remember_fonts(self, &reg);` (notice, first statement of `RenderBackend::register_window`): stores the handle every window of this backend already has (`reg.resource_cache.fonts`).
- `stealth_shared_fonts::clear_when_window_left(self, &msg);` (notice, first statement of `RenderBackend::process_scene_builder_result`): for `ClearNamespace` with no window under that id, clears the shared fonts of the namespace. It runs before Mozilla's `match` instead of inside the arm: between the head of the function and the arm there is only `tracy_rs::profile_scope!`, and the arm's remaining work (`documents.retain`, `document_to_window.retain`) touches maps that are not the shared font maps, which have their own lock per call, so the order between the two is not observable.

`render_backend_pool.rs`, `resource_cache.rs` and `rasterizer.rs` are Mozilla's text again.
