import colorsys, hashlib, json, os, re, shutil, struct, sys, time, xml.etree.ElementTree as ET, zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

import requests
from tqdm import tqdm

SNAP_DEFAULTS = {"Content": None, "IsSaved": False, "Media IDs": "", "Type": "snap"}
SNAP_KEYS = ["From", "Media Type", "Created", "Conversation Title", "IsSender", "Created(microseconds)"]
TARGET_JSON = {"chat_history.json", "snap_history.json", "friends.json"}
TIMESTAMP_MATCH_THRESHOLD = 30_000  # max ms proximity for timestamp matching
MEDIA_PENALTY = 5_000               # penalty per existing match to spread media
AVATAR_SIZE = 54
_GHOST_SVG = Path(__file__).parent / "ghost.svg"
GHOST_PATH = ET.parse(_GHOST_SVG).find(".//{http://www.w3.org/2000/svg}path").get("d")
SVG_NS = {"svg": "http://www.w3.org/2000/svg", "xlink": "http://www.w3.org/1999/xlink"}


def get_mtime(info):
    """Extract UTC mtime from ZipInfo central directory 0x5455 extra field."""
    extra = info.extra
    i = 0
    while i + 4 <= len(extra):
        tag, size = struct.unpack_from("<HH", extra, i)
        i += 4
        if tag == 0x5455 and size >= 5 and extra[i] & 1:
            return struct.unpack_from("<I", extra, i + 1)[0]
        i += size
    return time.mktime(info.date_time + (0, 0, -1))


def extract_zips(input_dir, tmp_dir):
    """Extract json/ and chat_media/ from zips, preserving real timestamps."""
    zips = sorted(input_dir.glob("*.zip"))
    if not zips:
        sys.exit("No zip files found in 'input'.")

    primary = [z for z in zips if not re.search(r"-\d+\.zip$", z.name)]
    secondary = sorted(
        [z for z in zips if re.search(r"-\d+\.zip$", z.name)],
        key=lambda z: int(re.search(r"-(\d+)\.zip$", z.name).group(1)),
    )

    all_zips = primary + secondary
    for zf_path in tqdm(all_zips, desc="Extracting zips", leave=False):
        with zipfile.ZipFile(zf_path) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                parts = Path(info.filename).parts
                is_json = len(parts) > 1 and parts[-2] == "json" and parts[-1] in TARGET_JSON
                is_media = "chat_media" in parts

                if not (is_json or is_media):
                    continue

                if is_json:
                    dest = tmp_dir / "json" / parts[-1]
                else:
                    idx = parts.index("chat_media")
                    dest = tmp_dir / Path(*parts[idx:])

                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(info.filename))
                mtime = get_mtime(info)
                os.utime(dest, (mtime, mtime))


def load_display_names(json_dir):
    """Parse friends.json to map Username -> Display Name."""
    path = json_dir / "friends.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            e["Username"]: e.get("Display Name", "")
            for cat in data.values() if isinstance(cat, list)
            for e in cat if isinstance(e, dict) and "Username" in e
        }
    except Exception:
        return {}


def find_owner(chat_data, snap_data):
    """Identify account owner from first outgoing message."""
    for conv in [*chat_data.values(), *snap_data.values()]:
        for m in conv:
            if m.get("IsSender"):
                return m.get("From", "unknown_user")
    return "unknown_user"


def build_days(chat_data, snap_data):
    """Organize all messages into a days[date][conv_id] structure."""
    days = defaultdict(lambda: defaultdict(list))
    usernames = set()
    group_info = []
    group_titles = {}

    for c_id, msgs in chat_data.items():
        participants, title = set(), None
        for m in msgs:
            m["Type"] = "message"
            days[m["Created"][:10]][c_id].append(m)
            if f := m.get("From"):
                usernames.add(f)
                participants.add(f)
            title = title or m.get("Conversation Title")
        if "-" in c_id:
            group_titles[c_id] = title or c_id
            group_info.append({"group_id": c_id, "name": title or c_id, "members": sorted(participants)})
        else:
            usernames.add(c_id)

    for c_id, msgs in snap_data.items():
        for m in msgs:
            days[m["Created"][:10]][c_id].append({k: m.get(k) for k in SNAP_KEYS} | SNAP_DEFAULTS)
            if f := m.get("From"):
                usernames.add(f)
            if "-" in c_id and c_id not in group_titles:
                t = m.get("Conversation Title")
                if t:
                    group_titles[c_id] = t
        if "-" not in c_id:
            usernames.add(c_id)

    return days, usernames, group_info, group_titles


def match_media(days, media_dir):
    """Scan media, pair overlays by mtime bucket, match all files to messages by timestamp."""
    media_files, overlay_files = [], []
    for f in (media_dir.iterdir() if media_dir.exists() else []):
        if not f.is_file() or "thumbnail" in f.name.lower():
            continue
        if "_overlay~" in f.name:
            overlay_files.append(f)
        elif "_media~" in f.name or re.search(r"_b~.+\.\w+$", f.name):
            media_files.append(f)

    # Pair overlays by mtime bucket (same second = same snap event, overlays are duplicates)
    overlay_pairs = {}
    mtime_buckets = defaultdict(lambda: [[], []])
    for f in media_files:
        if "_media~" in f.name:
            mtime_buckets[int(f.stat().st_mtime)][0].append(f)
    for f in overlay_files:
        mtime_buckets[int(f.stat().st_mtime)][1].append(f)
    for ms, ovs in mtime_buckets.values():
        for i, m in enumerate(ms):
            if ovs:
                overlay_pairs[m.name] = ovs[i % len(ovs)]

    # Sort messages then match each file to closest message by timestamp
    for day_convs in days.values():
        for msgs in day_convs.values():
            msgs.sort(key=lambda x: x.get("Created(microseconds)", 0))

    matched = 0
    for f in tqdm(media_files, desc="Matching media", leave=False):
        day, mtime_ms = f.name[:10], int(f.stat().st_mtime * 1000)
        best, best_diff, best_real = None, float("inf"), float("inf")
        for offset in (0, -1, 1):
            target = str(date.fromisoformat(day) + timedelta(offset))
            for msgs in days.get(target, {}).values():
                for m in msgs:
                    real_diff = abs(m.get("Created(microseconds)", 0) - mtime_ms)
                    ranked_diff = real_diff + len(m.get("media_filenames", [])) * MEDIA_PENALTY
                    if ranked_diff < best_diff:
                        best, best_diff, best_real = m, ranked_diff, real_diff
        if best and best_real <= TIMESTAMP_MATCH_THRESHOLD:
            best.setdefault("media_filenames", []).append(f.name)
            matched += 1

    return media_files, overlay_pairs, matched


def _media_type(ext):
    """Map file extension to a media type string."""
    ext = ext.lower().lstrip(".")
    if ext in ("jpg", "jpeg", "png", "gif", "webp"):
        return "IMAGE"
    if ext in ("mp4", "mov", "avi", "webm"):
        return "VIDEO"
    if ext in ("mp3", "aac", "m4a", "wav", "ogg"):
        return "AUDIO"
    return "IMAGE"


def _copy_message_media(m, media_dir, folder, overlay_pairs):
    """Copy media files for a single message, return set of copied filenames."""
    fnames = m.get("media_filenames", [])
    if not fnames:
        return set()

    rel_paths, copied = [], set()
    for fname in fnames:
        src = media_dir / fname
        if not src.exists():
            continue
        copied.add(fname)

        if fname in overlay_pairs:
            dest = folder / "media" / src.stem
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / fname)
            shutil.copy2(overlay_pairs[fname], dest / overlay_pairs[fname].name)
            rel_paths.append(f"media/{src.stem}")
        else:
            (folder / "media").mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, folder / "media" / fname)
            rel_paths.append(f"media/{fname}")

    if rel_paths:
        m["media_locations"] = rel_paths

    return copied


def _collect_orphans(day, media_by_day, day_mapped, folder):
    """Detect and copy orphaned media for a day, returning the orphan list."""
    orphaned = []
    for fname, f in sorted(media_by_day.get(day, {}).items()):
        if fname not in day_mapped:
            ext = f.suffix.lstrip(".")
            orphan_dir = folder / "orphaned"
            orphan_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, orphan_dir / fname)
            orphaned.append({
                "path": f"orphaned/{fname}",
                "filename": fname,
                "type": _media_type(ext),
                "extension": ext,
            })
    return orphaned


def write_output(days, overlay_pairs, media_dir, out, group_titles, all_media_files):
    """Write a single conversations.json per day with stats and orphaned media."""
    days_out = out / "days"
    if days_out.exists():
        shutil.rmtree(days_out)

    media_by_day = defaultdict(dict)
    for f in all_media_files:
        media_by_day[f.name[:10]][f.name] = f

    sorted_days = sorted(days.items())
    for day, convs in tqdm(sorted_days, desc="Writing output", leave=False):
        folder = days_out / day
        folder.mkdir(parents=True, exist_ok=True)

        conversations = []
        day_media_count = 0
        day_mapped = set()

        for c_id, msgs in convs.items():
            for m in msgs:
                copied = _copy_message_media(m, media_dir, folder, overlay_pairs)
                day_mapped.update(copied)
                day_media_count += len(copied)

            is_group = "-" in c_id
            conv_entry = {"id": c_id, "conversation_id": c_id,
                          "conversation_type": "group" if is_group else "individual", "messages": msgs}
            if is_group:
                conv_entry["group_name"] = group_titles.get(c_id, c_id)
            conversations.append(conv_entry)

        orphaned = _collect_orphans(day, media_by_day, day_mapped, folder)

        (folder / "conversations.json").write_text(json.dumps({
            "date": day,
            "stats": {
                "conversationCount": len(conversations),
                "messageCount": sum(len(msgs) for msgs in convs.values()),
                "mediaCount": day_media_count,
            },
            "conversations": conversations,
            "orphanedMedia": {"orphaned_media_count": len(orphaned), "orphaned_media": orphaned},
        }, indent=2, ensure_ascii=False), encoding="utf-8")

    return len(sorted_days)


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


def generate_bitmoji_assets(usernames, output_root):
    """Fetch and save Bitmoji avatars, returning {username: relative_path}."""
    if not usernames:
        return {}
    bitmoji_dir = output_root / "bitmoji"
    bitmoji_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    with ThreadPoolExecutor(max_workers=min(8, len(usernames))) as pool:
        futures = [pool.submit(_fetch_avatar, u) for u in usernames]
        with tqdm(total=len(usernames), desc="Fetching avatars", leave=False) as pbar:
            for f in as_completed(futures):
                username, svg = f.result()
                filename = f"{username}.svg"
                (bitmoji_dir / filename).write_text(svg, encoding="utf-8")
                paths[username] = f"bitmoji/{filename}"
                pbar.update(1)
    return paths


def main():
    input_dir, tmp_dir = Path("input"), Path("_tmp_extract")
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)

    extract_zips(input_dir, tmp_dir)

    json_dir = tmp_dir / "json"
    media_dir = tmp_dir / "chat_media"
    chat_data = json.loads((json_dir / "chat_history.json").read_text(encoding="utf-8"))
    snap_data = json.loads((json_dir / "snap_history.json").read_text(encoding="utf-8"))

    owner = find_owner(chat_data, snap_data)
    days, usernames, group_info, group_titles = build_days(chat_data, snap_data)
    usernames.add(owner)

    media_files, overlay_pairs, matched = match_media(days, media_dir)

    out = Path("output")
    total_files = write_output(days, overlay_pairs, media_dir, out, group_titles, media_files)

    # Index & Bitmoji
    display_map = load_display_names(json_dir)
    valid_usernames = {u for u in usernames if u}
    bitmoji_paths = generate_bitmoji_assets(valid_usernames, out)
    users = [
        {"username": u, "display_name": display_map.get(u, u), "bitmoji": bitmoji_paths.get(u, f"bitmoji/{u}.svg")}
        for u in sorted(usernames) if u
    ]
    (out / "index.json").write_text(
        json.dumps({"account_owner": owner, "users": users, "groups": group_info}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Detected Account Owner: {owner}")
    print(f"Done. {total_files} day files across {len(days)} days.")
    print(f"Media matched: {matched}/{len(media_files)} ({matched/max(len(media_files),1)*100:.1f}%)")

    shutil.rmtree(tmp_dir)


if __name__ == "__main__":
    main()