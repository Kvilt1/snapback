# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Snapback is a Python data processing pipeline that extracts, parses, and organizes Snapchat account data exports into structured, queryable JSON output. It processes ZIP archives from Snapchat's official data download, matching media files to messages and generating Bitmoji avatars.

## Running

```bash
# Run the full pipeline (no build step needed)
python splitter.py

# Dependencies (no requirements.txt - install manually)
pip install requests urllib3 tqdm
```

There are no tests, linting, or CI/CD configurations.

## Architecture

The pipeline flows through `splitter.py:main()` in sequential phases:

1. **Extraction** (`extract_zips`): Unzips Snapchat data exports from `input/`, preserving UTC timestamps via custom binary parsing of ZIP extended timestamp headers
2. **Parsing**: Loads `chat_history.json`, `snap_history.json`, `friends.json` into memory
3. **Organization** (`build_days`): Groups messages by date and conversation ID into a `days[date][conv_id][messages]` structure
4. **Media Classification** (`classify_media`): Categorizes files from `chat_media/` into ID-keyed lookups, overlays, and other files
5. **Media Matching** (`match_media`): Two-pass strategy — first by explicit Media IDs in message metadata, then by timestamp proximity (±1 day, within 30 seconds)
6. **Output** (`write_output`): Generates `output/days/YYYY-MM-DD/conversations.json` with linked media
7. **Avatars** (`generate_bitmoji_assets` in `bitmoji.py`): Parallel fetches from Snapchat API with deterministic colored-ghost SVG fallback
8. **Indexing**: Creates `output/index.json` with user/group metadata

## Module Responsibilities

- **`splitter.py`**: Core pipeline orchestration — extraction, parsing, organization, media matching, output generation. Contains `Progress` class for dual tqdm progress bars (phase detail + overall phase tracker). Constants (`TIMESTAMP_MATCH_THRESHOLD`, `MEDIA_PENALTY`, `PROGRESS_DELAY`) are defined at module level
- **`bitmoji.py`**: Thread-safe avatar fetching with `ThreadPoolExecutor` and deterministic colored-ghost SVG fallback using SHA256-based HSL colors. Accepts optional `progress` parameter for unified progress tracking

## Key Design Decisions

- **Two-pass media matching**: ID-based first, timestamp-proximity fallback second — handles both structured and ambiguous media references
- **Deterministic fallback avatars**: Username → SHA256 → HSL color ensures reproducible, visually distinct colors
- **Groups detected by pattern**: Conversation IDs containing `-` indicate group chats
- **Entire history in memory**: No streaming/incremental processing — works for typical personal account sizes
- **Dual progress bars**: `Progress` class in `splitter.py` manages two tqdm bars — a per-phase detail bar (position 1, teal) and an overall phase counter (position 0, purple). Uses `delay=0.2` to skip rendering for instant phases, `leave=False` so bars vanish before final stats print. Phase names are defined in `PHASE_NAMES` constant

## Data Flow

```
input/*.zip → extract → temp dir (json/, chat_media/)
                          ↓
              parse chat/snap/friends JSON
                          ↓
              build_days() → days[date][conv][msgs]
                          ↓
              classify_media() + match_media() → enrich messages
                          ↓
              write_output() → output/days/YYYY-MM-DD/
              generate_bitmoji_assets() → output/bitmoji/
              index.json → output/index.json
```
