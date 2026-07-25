#!/usr/bin/env python3
"""Emit per-browser builds of the SunoSync token-helper extension.

The extension source is shared; only the manifest differs. Chrome MV3 wants
``background.service_worker``, which Firefox does not implement — Firefox MV3
uses ``background.scripts`` and additionally requires a
``browser_specific_settings.gecko.id``. Firefox's "Load Temporary Add-on" also
insists the file be named ``manifest.json``, so the Firefox variant cannot just
live alongside the Chrome one; it has to be assembled into its own directory.

Usage::

    python scripts/build_extension.py            # build both
    python scripts/build_extension.py --target firefox
    python scripts/build_extension.py --zip      # also produce .zip archives

Output lands in ``dist/extension-<target>/``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = REPO_ROOT / "browser_extension"
DIST_DIR = REPO_ROOT / "dist"

# Files copied verbatim into every build.
SHARED_FILES = [
    "background.js",
    "content.js",
    "injected.js",
    "popup.html",
    "popup.js",
]
SHARED_DIRS = ["icons"]

MANIFESTS = {
    "chrome": "manifest.json",
    "firefox": "manifest.firefox.json",
}


def _validate_manifest(path: Path, target: str) -> dict:
    """Load a manifest and check the browser-specific bits are right."""
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read {path.name}: {exc}") from exc

    background = manifest.get("background", {})

    if target == "chrome":
        if "service_worker" not in background:
            raise SystemExit(
                "Chrome manifest must declare background.service_worker."
            )
    elif target == "firefox":
        if "scripts" not in background:
            raise SystemExit(
                "Firefox manifest must declare background.scripts; "
                "Firefox MV3 does not support service_worker."
            )
        gecko_id = (
            manifest.get("browser_specific_settings", {}).get("gecko", {}).get("id")
        )
        if not gecko_id:
            raise SystemExit(
                "Firefox manifest must set browser_specific_settings.gecko.id, "
                "otherwise the add-on cannot be installed."
            )

    # Every script the manifest references must actually exist.
    referenced = list(background.get("scripts", []))
    if "service_worker" in background:
        referenced.append(background["service_worker"])
    for entry in manifest.get("content_scripts", []):
        referenced.extend(entry.get("js", []))
    for entry in manifest.get("web_accessible_resources", []):
        referenced.extend(entry.get("resources", []))

    missing = [name for name in referenced if not (SOURCE_DIR / name).exists()]
    if missing:
        raise SystemExit(f"{path.name} references missing file(s): {', '.join(missing)}")

    return manifest


def build(target: str, make_zip: bool = False) -> Path:
    manifest_name = MANIFESTS[target]
    manifest_path = SOURCE_DIR / manifest_name
    manifest = _validate_manifest(manifest_path, target)

    out_dir = DIST_DIR / f"extension-{target}"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    for name in SHARED_FILES:
        shutil.copy2(SOURCE_DIR / name, out_dir / name)
    for name in SHARED_DIRS:
        shutil.copytree(SOURCE_DIR / name, out_dir / name)

    # Always written as manifest.json, whatever the source file was called.
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=4) + "\n", encoding="utf-8"
    )

    print(f"Built {target} extension -> {out_dir.relative_to(REPO_ROOT)}")

    if make_zip:
        archive = DIST_DIR / f"sunosync-extension-{target}-{manifest['version']}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(out_dir.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(out_dir))
        print(f"  packaged -> {archive.relative_to(REPO_ROOT)}")

    return out_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        choices=[*MANIFESTS, "all"],
        default="all",
        help="Which browser to build for (default: all).",
    )
    parser.add_argument(
        "--zip", action="store_true", help="Also produce a .zip archive per target."
    )
    args = parser.parse_args(argv)

    if not SOURCE_DIR.is_dir():
        raise SystemExit(f"Extension source not found at {SOURCE_DIR}")

    targets = list(MANIFESTS) if args.target == "all" else [args.target]
    DIST_DIR.mkdir(exist_ok=True)

    for target in targets:
        build(target, make_zip=args.zip)

    return 0


if __name__ == "__main__":
    sys.exit(main())
