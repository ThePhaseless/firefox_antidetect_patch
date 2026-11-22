/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

//! The fonts a window left in the resources every window of its pool shares.
//!
//! A window's `ResourceCache` takes a namespace's fonts out of the shared font resources when the
//! namespace is cleared. `ApiMsg::UnregisterWindow` goes on the direct channel and
//! `SceneBuilderResult::ClearNamespace` through the low-priority scene builder, so the window is often
//! gone before its `ClearNamespace` arrives: the window took its resource cache with it, nobody would ever
//! take those fonts out, and they stayed in the pool for as long as it lives (a web font of a closed page
//! is up to a few MB, kept once per distinct font).
//!
//! The render backend remembers the shared font resources of its windows (`RememberedFonts`, set when a
//! window is registered: every window of a backend is handed the same instance, the one of the pool) and,
//! for a `ClearNamespace` whose window is no longer registered, clears them itself.
//!
//! The module is a child of `render_backend`: it reads the backend's private `windows` and calls its private
//! `process_scene_builder_result` (in the tests).
//!
//! Mozilla's methods this depends on (all `pub`): `FontTemplateMap::clear_namespace`,
//! `FontTemplateMap::delete_fonts`, `FontInstanceMap::clear_namespace`, `FontInstanceMap::delete_font_instances`,
//! `FontInstanceKeyMap::clear_namespace` and `FontKeyMap::clear_namespace`: the steps of
//! `ResourceCache::clear_namespace` that work on the shared resources, in the same order.

use api::IdNamespace;
use api::FontKey;
use api::FontInstanceKey;
use glyph_rasterizer::SharedFontResources;

use crate::render_api::WindowRegistration;
use crate::render_backend::RenderBackend;
use crate::scene_builder_thread::SceneBuilderResult;

/// The shared font resources of the windows of a render backend: empty until the first window is registered.
pub struct RememberedFonts(Option<SharedFontResources>);

impl RememberedFonts {
    pub fn empty() -> RememberedFonts {
        RememberedFonts(None)
    }

    fn remember(&mut self, fonts: &SharedFontResources) {
        self.0 = Some(fonts.clone());
    }
}

/// What `clear_shared_fonts` took out, for whoever owns the glyph rasterizer and the glyph cache, which are
/// not shared. The backend itself has no window to remove them from, so only the tests read it.
#[allow(dead_code)]
pub struct ClearedFonts {
    /// The font keys of the namespace's own templates (not shared with another namespace).
    pub local_font_keys: Vec<FontKey>,
    /// The shared font keys that no namespace refers to any more.
    pub shared_font_keys: Vec<FontKey>,
    /// The shared font instance keys that no namespace refers to any more.
    pub shared_instance_keys: Vec<FontInstanceKey>,
}

/// A window is being registered on the backend: its shared font resources are the ones to clear when one
/// of its namespaces is cleared after the window left.
pub(super) fn remember_fonts(backend: &mut RenderBackend, reg: &WindowRegistration) {
    backend.stealth_fonts.remember(&reg.resource_cache.fonts);
}

/// A scene builder result arrived at the backend: for `ClearNamespace(backend_id, id)` with no window
/// registered under `backend_id`, takes the namespace's fonts out of the shared resources, as the window's
/// resource cache would have. Any other message, or a window that is still registered (its own resource cache
/// clears them, in Mozilla's arm): nothing.
pub(super) fn clear_when_window_left(backend: &mut RenderBackend, msg: &SceneBuilderResult) {
    if let SceneBuilderResult::ClearNamespace(backend_id, id) = msg {
        if !backend.windows.contains_key(backend_id) {
            if let Some(fonts) = backend.stealth_fonts.0.as_mut() {
                clear_shared_fonts(fonts, *id);
            }
        }
    }
}

/// Takes everything a namespace put in the shared font resources out of them: its own templates and
/// instances, its mappings to shared keys, and the shared templates and instances that were left with no
/// mapping.
///
/// This is the part of clearing a namespace that does not need a window: a namespace's fonts live in the
/// resources every window of a pool shares, and a namespace whose window was unregistered before its
/// `ClearNamespace` arrived has no resource cache to clear them through.
pub fn clear_shared_fonts(fonts: &mut SharedFontResources, namespace: IdNamespace) -> ClearedFonts {
    // First clear out any non-shared resources associated with the namespace.
    fonts.instances.clear_namespace(namespace);
    let local_font_keys = fonts.templates.clear_namespace(namespace);

    // Then any shared instance keys that were remapped from the namespace.
    let shared_instance_keys = fonts.instance_keys.clear_namespace(namespace);
    fonts.instances.delete_font_instances(&shared_instance_keys);

    // Finally any shared font keys that were remapped from the namespace.
    let shared_font_keys = fonts.font_keys.clear_namespace(namespace);
    fonts.templates.delete_fonts(&shared_font_keys);

    ClearedFonts { local_font_keys, shared_font_keys, shared_instance_keys }
}

#[cfg(test)]
mod tests {
    use super::*;
    use api::channel::unbounded_channel;
    use api::{FontTemplate, RenderBackendId};
    use crate::render_api::ApiMsg;
    use crate::scene_builder_thread::SceneBuilderRequest;
    use std::sync::Arc;

    fn backend_with_a_font_of(namespace: u32) -> (RenderBackend, SharedFontResources) {
        let mut fonts = SharedFontResources::new(IdNamespace(0));
        let key = FontKey::new(IdNamespace(namespace), 1);
        let template = FontTemplate::Raw(Arc::new(vec![1, 2, 3, 4]), 0);
        let shared = fonts.font_keys.add_key(&key, &template).expect("a first font gets a shared key");
        fonts.templates.add_font(shared, template);
        let (_api_tx, api_rx) = unbounded_channel::<ApiMsg>();
        let (scene_tx, _scene_rx) = unbounded_channel::<SceneBuilderRequest>();
        let mut backend = RenderBackend::new(api_rx, scene_tx, None, false);
        backend.stealth_fonts.remember(&fonts);
        (backend, fonts)
    }

    /// The message the scene builder sends the backend when a `RenderApi` was dropped, for a backend
    /// that has no window registered under that id: `UnregisterWindow` came first.
    #[test]
    fn the_fonts_of_a_namespace_leave_the_shared_resources_when_its_window_is_gone() {
        let (mut backend, fonts) = backend_with_a_font_of(7);
        assert_eq!(fonts.templates.len(), 1);

        let mut frames = 0;
        backend.process_scene_builder_result(
            SceneBuilderResult::ClearNamespace(RenderBackendId(1), IdNamespace(7)),
            &mut frames,
        );

        assert_eq!(fonts.templates.len(), 0, "the font of a namespace whose window left stays in the pool for good");
    }

    #[test]
    fn the_fonts_of_another_namespace_stay() {
        let (mut backend, fonts) = backend_with_a_font_of(7);

        let mut frames = 0;
        backend.process_scene_builder_result(
            SceneBuilderResult::ClearNamespace(RenderBackendId(1), IdNamespace(8)),
            &mut frames,
        );

        assert_eq!(fonts.templates.len(), 1);
    }

    /// What a window's resource cache does when a font is added: map the key to a shared key
    /// (one per distinct bytes), and store the template once.
    fn add(fonts: &mut SharedFontResources, namespace: u32, id: u32, bytes: &[u8]) {
        let key = FontKey::new(IdNamespace(namespace), id);
        let template = FontTemplate::Raw(Arc::new(Vec::from(bytes)), 0);
        if let Some(shared) = fonts.font_keys.add_key(&key, &template) {
            fonts.templates.add_font(shared, template);
        }
    }

    #[test]
    fn a_namespace_takes_its_fonts_out_of_the_shared_resources() {
        let mut fonts = SharedFontResources::new(IdNamespace(0));
        add(&mut fonts, 7, 1, b"font one");
        add(&mut fonts, 7, 2, b"font two");
        assert_eq!(fonts.templates.len(), 2);

        let cleared = clear_shared_fonts(&mut fonts, IdNamespace(7));

        assert_eq!(fonts.templates.len(), 0, "the templates of the namespace stay in the shared resources");
        assert!(fonts.font_keys.keys().is_empty());
        assert_eq!(cleared.shared_font_keys.len(), 2);
    }

    #[test]
    fn a_font_two_namespaces_have_stays_until_the_last_one_is_cleared() {
        let mut fonts = SharedFontResources::new(IdNamespace(0));
        add(&mut fonts, 7, 1, b"the same bytes");
        add(&mut fonts, 8, 1, b"the same bytes");
        assert_eq!(fonts.templates.len(), 1, "the bytes are stored once");

        let first = clear_shared_fonts(&mut fonts, IdNamespace(7));
        assert_eq!(fonts.templates.len(), 1);
        assert!(first.shared_font_keys.is_empty());

        let last = clear_shared_fonts(&mut fonts, IdNamespace(8));
        assert_eq!(fonts.templates.len(), 0);
        assert_eq!(last.shared_font_keys.len(), 1);
    }

    #[test]
    fn another_namespace_is_not_touched() {
        let mut fonts = SharedFontResources::new(IdNamespace(0));
        add(&mut fonts, 7, 1, b"font of seven");
        add(&mut fonts, 8, 1, b"font of eight");

        clear_shared_fonts(&mut fonts, IdNamespace(7));

        assert_eq!(fonts.templates.len(), 1);
        assert_eq!(fonts.font_keys.keys().len(), 1);
    }
}
