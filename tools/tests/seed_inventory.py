"""The inventory of a fake series, as the series keeps it: the `inventory` of each folder's MANIFEST.json (there is no other copy).

    seed_inventory(root, records, default_folder=None)    add the records to the MANIFEST.json of their folder (written if the folder has none)
    set_inventory(root, records, default_folder=None)     the same after every folder's `inventory` is emptied: the records are the whole inventory
"""
import json
from pathlib import Path

import engine


def seed_inventory(root, records, default_folder=None):
    root = Path(root)
    by_folder = {}
    for r in records:
        folder = engine.record_folder(r) or default_folder
        by_folder.setdefault(folder, []).append(r)
    for folder, recs in by_folder.items():
        path = root / folder / "MANIFEST.json"
        manifest = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"modified": [], "added": {}, "sha256": {}}
        manifest["inventory"] = manifest.get("inventory", []) + recs
        path.parent.mkdir(parents=True, exist_ok=True)
        engine.write_json(path, manifest)


def set_inventory(root, records, default_folder=None):
    root = Path(root)
    for path in root.glob("*/**/MANIFEST.json"):
        if "src" in path.relative_to(root).parts:
            continue
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("inventory"):
            manifest["inventory"] = []
            engine.write_json(path, manifest)
    seed_inventory(root, records, default_folder)
