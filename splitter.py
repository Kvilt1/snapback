import json, os, re, shutil, struct, sys, time, zipfile
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from tqdm import tqdm

from bitmoji import generate_bitmoji_assets

SNAP_DEFAULTS = {"Content": None, "IsSaved": False, "Media IDs": "", "Type": "snap"}
SNAP_KEYS = ["From", "Media Type", "Created", "Conversation Title", "IsSender", "Created(microseconds)"]
TARGET_JSON = {"chat_history.json", "snap_history.json", "friends.json"}
PHASE_NAMES = ["Extracting zips", "Matching by media ID", "Matching by timestamp", "Writing output", "Fetching avatars"]


class Progress:
    """Two-bar progress display: phase detail on top, overall phases on bottom."""
    def __init__(self):
        self._phase = 0
        self._bar = None
        self._overall = tqdm(
            total=len(PHASE_NAMES), unit="phase", position=0, leave=False,
            desc="Overall", bar_format="{desc}: {bar} {n_fmt}/{total_fmt} phases [{elapsed}]",
        )

    def phase(self, total, unit="it"):
        if self._bar:
            self._bar.close()
            self._overall.update(1)
        self._phase += 1
        desc = PHASE_NAMES[self._phase - 1] if self._phase <= len(PHASE_NAMES) else f"Phase {self._phase}"
        self._overall.set_description(f"Overall ({desc})")
        self._overall.refresh()
        self._bar = tqdm(
            total=total, unit=unit, delay=0.2, leave=False, position=1,
            desc=f"  [{self._phase}/{len(PHASE_NAMES)}] {desc}",
        )

    def update(self, n=1):
        if self._bar:
            self._bar.update(n)

    def close(self):
        if self._bar:
            self._bar.close()
            self._overall.update(1)
            self._bar = None
        self._overall.close()


def get_local_mtime(raw, info):
    """Read LOCAL file header extended timestamp (0x5455) for accurate UTC mtime."""
    try:
        raw.seek(info.header_offset + 26)
        fn_len, ex_len = struct.unpack("<HH", raw.read(4))
        raw.seek(fn_len, 1)
        extra = raw.read(ex_len)
        i = 0
        while i + 4 <= len(extra):
            tag, size = struct.unpack_from("<HH", extra, i)
            i += 4
            if tag == 0x5455 and size >= 5 and extra[i] & 1:
                return struct.unpack_from("<I", extra, i + 1)[0]
            i += size
    except Exception:
        pass
    return time.mktime(info.date_time + (0, 0, -1))


def extract_zips(input_dir, tmp_dir, progress):
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
    progress.phase(len(all_zips), "zip")
    for zf_path in all_zips:
        with zipfile.ZipFile(zf_path) as zf, open(zf_path, "rb") as raw:
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
                mtime = get_local_mtime(raw, info)
                os.utime(dest, (mtime, mtime))
        progress.update(1)


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


def classify_media(media_dir):
    """Classify media files into b-lookup, other files, and overlay pairs."""
    b_lookup, other_files = {}, []
    groups = defaultdict(lambda: {"media": [], "overlay": [], "media_zip": [], "overlay_zip": []})

    for f in (media_dir.iterdir() if media_dir.exists() else []):
        if not f.is_file() or "thumbnail" in f.name.lower():
            continue

        day = f.name[:10]
        is_zip = "~zip-" in f.name

        if "_overlay~" in f.name:
            groups[day]["overlay_zip" if is_zip else "overlay"].append(f)
        elif "_media~" in f.name:
            groups[day]["media_zip" if is_zip else "media"].append(f)
            other_files.append(f)
        elif m := re.search(r"_b~(.+)\.\w+$", f.name):
            b_lookup[m.group(1)] = f

    # Pair media files with their overlays (same day, same count, sorted)
    overlay_pairs = {}
    for g in groups.values():
        for kind in ("media", "media_zip"):
            ms = sorted(g[kind], key=lambda x: x.name)
            os_ = sorted(g[kind.replace("media", "overlay")], key=lambda x: x.name)
            if ms and len(ms) == len(os_):
                overlay_pairs.update(dict(zip((m.name for m in ms), os_)))

    return b_lookup, other_files, overlay_pairs


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


def match_media(days, b_lookup, other_files, progress):
    """Match media files to messages by ID then by timestamp proximity."""
    total_ids = matched_ids = 0
    matched_b = set()

    # Pass 1: Match by media ID
    progress.phase(len(days), "day")
    for day_convs in days.values():
        for msgs in day_convs.values():
            msgs.sort(key=lambda x: x.get("Created(microseconds)", 0))
            for m in msgs:
                ids = [i.strip().removeprefix("b~") for i in m.get("Media IDs", "").split(",") if i.strip()]
                total_ids += len(ids)
                for mid in ids:
                    if mid in b_lookup:
                        m.setdefault("media_filenames", []).append(b_lookup[mid].name)
                        matched_b.add(mid)
                        matched_ids += 1
        progress.update(1)

    # Pass 2: Match remaining files by timestamp proximity
    ts_files = [
        (f.name[:10], int(f.stat().st_mtime * 1000), f)
        for mid, f in b_lookup.items() if mid not in matched_b
    ] + [(f.name[:10], int(f.stat().st_mtime * 1000), f) for f in other_files]

    matched_ts = 0
    progress.phase(len(ts_files), "file")
    for day, mtime_ms, f in ts_files:
        best, best_diff, best_real = None, float("inf"), float("inf")
        for offset in (0, -1, 1):
            target = str(date.fromisoformat(day) + timedelta(offset))
            for msgs in days.get(target, {}).values():
                for m in msgs:
                    real_diff = abs(m.get("Created(microseconds)", 0) - mtime_ms)
                    # Penalize messages that already have media so nearby
                    # duplicates get their share instead of one hoarding all
                    ranked_diff = real_diff + len(m.get("media_filenames", [])) * 5_000
                    if ranked_diff < best_diff:
                        best, best_diff, best_real = m, ranked_diff, real_diff
        if best and best_real <= 30_000:
            best.setdefault("media_filenames", []).append(f.name)
            matched_ts += 1
        progress.update(1)

    return total_ids, matched_ids, matched_b, matched_ts, ts_files


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


def write_output(days, overlay_pairs, media_dir, out, group_titles, all_media_files, progress):
    """Write a single conversations.json per day with stats and orphaned media."""
    days_out = out / "days"
    if days_out.exists():
        shutil.rmtree(days_out)

    # Index all media files by their date prefix
    media_by_day = defaultdict(dict)
    for f in all_media_files:
        media_by_day[f.name[:10]][f.name] = f

    mapped_names = set()
    total_day_files = 0

    sorted_days = sorted(days.items())
    progress.phase(len(sorted_days), "day")
    for day, convs in sorted_days:
        folder = days_out / day
        folder.mkdir(parents=True, exist_ok=True)

        conversations = []
        day_msg_count = 0
        day_media_count = 0
        day_mapped = set()

        for c_id, msgs in convs.items():
            is_group = "-" in c_id
            conv_type = "group" if is_group else "individual"

            for m in msgs:
                fnames = m.get("media_filenames", [])
                if not fnames:
                    continue

                rel_paths = []
                matched_files = []
                any_grouped = False

                for fname in fnames:
                    src = media_dir / fname
                    if not src.exists():
                        continue
                    mapped_names.add(fname)
                    day_mapped.add(fname)
                    day_media_count += 1

                    rel_path = f"media/{fname}"
                    if fname in overlay_pairs:
                        dest = folder / "media" / src.stem
                        dest.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dest / fname)
                        shutil.copy2(overlay_pairs[fname], dest / overlay_pairs[fname].name)
                        rel_path = f"media/{src.stem}"
                        matched_files.append(src.stem)
                        any_grouped = True
                    else:
                        (folder / "media").mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, folder / "media" / fname)
                        matched_files.append(fname)

                    rel_paths.append(rel_path)

                if rel_paths:
                    m["media_locations"] = rel_paths
                    m["matched_media_files"] = matched_files
                    m["mapping_method"] = "media_id" if m.get("Media IDs", "").strip() else "timestamp"
                    m["is_grouped"] = any_grouped

            day_msg_count += len(msgs)

            conv_entry = {
                "id": c_id,
                "conversation_id": c_id,
                "conversation_type": conv_type,
                "messages": msgs,
            }
            if is_group:
                conv_entry["group_name"] = group_titles.get(c_id, c_id)

            conversations.append(conv_entry)

        # Collect orphaned media for this day
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

        day_data = {
            "date": day,
            "stats": {
                "conversationCount": len(conversations),
                "messageCount": day_msg_count,
                "mediaCount": day_media_count,
            },
            "conversations": conversations,
            "orphanedMedia": {
                "orphaned_media_count": len(orphaned),
                "orphaned_media": orphaned,
            },
        }

        (folder / "conversations.json").write_text(
            json.dumps(day_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        total_day_files += 1
        progress.update(1)

    return total_day_files, mapped_names



def pct(a, t):
    return f"{a}/{t} ({a / t * 100:.1f}%)" if t else "0/0"


def main():
    input_dir, tmp_dir = Path("input"), Path("_tmp_extract")
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)

    progress = Progress()
    extract_zips(input_dir, tmp_dir, progress)

    json_dir = tmp_dir / "json"
    media_dir = tmp_dir / "chat_media"
    chat_data = json.loads((json_dir / "chat_history.json").read_text(encoding="utf-8"))
    snap_data = json.loads((json_dir / "snap_history.json").read_text(encoding="utf-8"))

    owner = find_owner(chat_data, snap_data)

    b_lookup, other_files, overlay_pairs = classify_media(media_dir)
    days, usernames, group_info, group_titles = build_days(chat_data, snap_data)
    usernames.add(owner)

    total_ids, matched_ids, matched_b, matched_ts, ts_files = match_media(days, b_lookup, other_files, progress)

    out = Path("output")
    all_media_files = list(b_lookup.values()) + other_files
    total_files, mapped_names = write_output(days, overlay_pairs, media_dir, out, group_titles, all_media_files, progress)

    # Index & Bitmoji
    display_map = load_display_names(json_dir)
    valid_usernames = {u for u in usernames if u}
    progress.phase(len(valid_usernames), "user")
    bitmoji_paths = generate_bitmoji_assets(valid_usernames, out, progress)
    users = [
        {"username": u, "display_name": display_map.get(u, u), "bitmoji": bitmoji_paths.get(u, f"bitmoji/{u}.svg")}
        for u in sorted(usernames) if u
    ]
    (out / "index.json").write_text(
        json.dumps({"account_owner": owner, "users": users, "groups": group_info}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    progress.close()

    # Stats
    print(f"Detected Account Owner: {owner}")
    total_media = len(b_lookup) + len(other_files)
    print(f"Done. {total_files} day files across {len(days)} days.")
    print(f"Json Media IDs:      {pct(matched_ids, total_ids)}")
    print(f"Media file IDs:      {pct(len(matched_b), len(b_lookup))}")
    print(f"Timestamp mapping:   {pct(matched_ts, len(ts_files))}")
    print(f"Total mapping rate:  {pct(matched_ids + matched_ts, total_media)}")

    shutil.rmtree(tmp_dir)


if __name__ == "__main__":
    main()