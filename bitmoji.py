"""Fetch Snapchat Bitmoji avatars with colored-ghost fallback."""

import hashlib
import colorsys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

AVATAR_SIZE = 54
GHOST_PATH = (
    "M27 54.06C33.48 54.06 39.48 51.78 44.16 47.94C43.32 46.68 42.36 45.78 41.34 44.94C38.22 42.48 "
    "33.78 41.58 30.72 41.04L30.6 39.84C35.28 37.08 36.42 34.14 38.28 27.96L38.34 27.54C38.34 27.54 "
    "39.96 26.88 40.2 23.88C40.56 19.8 38.88 21 38.88 20.7C39.06 18.6 39 15.84 38.4 13.8C37.14 9.42 "
    "32.88 5.94 27 5.94C21.12 5.94 16.86 9.36 15.6 13.8C15 15.84 14.94 18.6 15.12 20.76C15.12 21.06 "
    "13.5 19.86 13.8 23.94C14.04 26.94 15.66 27.6 15.66 27.6L15.72 28.02C17.58 34.2 18.72 37.14 "
    "23.4 39.9L23.28 41.1C20.28 41.64 15.78 42.54 12.66 45C11.64 45.84 10.68 46.74 9.84 48C14.52 "
    "51.78 20.52 54.06 27 54.06Z"
)
SVG_NS = {"svg": "http://www.w3.org/2000/svg", "xlink": "http://www.w3.org/1999/xlink"}


def _fallback_svg(username):
    """Ghost SVG with a deterministic color derived from the username."""
    hue = int.from_bytes(hashlib.sha256(username.encode()).digest()[:2], "little") % 360
    r, g, b = colorsys.hls_to_rgb(hue / 360, 0.6, 0.3)
    fill = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
    return (
        f'<svg viewBox="0 0 {AVATAR_SIZE} {AVATAR_SIZE}" xmlns="http://www.w3.org/2000/svg">'
        f'<path d="{GHOST_PATH}" fill="{fill}" stroke="black" stroke-opacity="0.2" stroke-width="0.9"/>'
        f'</svg>'
    )


def _fetch_avatar(username):
    """Fetch a single Bitmoji SVG, returning fallback on any failure."""
    try:
        resp = requests.get(
            "https://app.snapchat.com/web/deeplink/snapcode",
            params={"username": username, "type": "SVG", "bitmoji": "enable"},
            timeout=10,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        img = root.find(".//svg:image", SVG_NS)
        if img is None:
            raise ValueError("No <image> in SVG")
        href = img.get(f"{{{SVG_NS['xlink']}}}href") or img.get("href")
        if not href:
            raise ValueError("No href on <image>")
        return username, (
            f'<svg viewBox="0 0 {AVATAR_SIZE} {AVATAR_SIZE}" xmlns="http://www.w3.org/2000/svg" '
            f'xmlns:xlink="http://www.w3.org/1999/xlink">'
            f'<image href="{href}" x="0" y="0" width="{AVATAR_SIZE}" height="{AVATAR_SIZE}"/>'
            f'</svg>'
        )
    except Exception:
        return username, _fallback_svg(username)


def generate_bitmoji_assets(usernames, output_root, progress=None):
    """Fetch and save Bitmoji avatars, returning {username: relative_path}."""
    if not usernames:
        return {}
    bitmoji_dir = output_root / "bitmoji"
    bitmoji_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    with ThreadPoolExecutor(max_workers=min(8, len(usernames))) as pool:
        futures = [pool.submit(_fetch_avatar, u) for u in usernames]
        for f in as_completed(futures):
            username, svg = f.result()
            filename = f"{username}.svg"
            (bitmoji_dir / filename).write_text(svg, encoding="utf-8")
            paths[username] = f"bitmoji/{filename}"
            if progress is not None:
                progress.update(1)
    return paths
