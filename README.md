# Snapback

A local Snapchat archive viewer. Processes your Snapchat data export into a browsable day-by-day chat viewer with a stats dashboard.

## How it works

**Phase 1 — `splitter.py`** reads your Snapchat ZIP export(s), correlates media files to messages by timestamp, fetches Bitmoji avatars, and writes one `conversations.json` + web viewer per calendar day into `output/days/`. It also generates `output/dashboard.html` with aggregate stats and an activity heatmap.

**Phase 2 — `web/`** is a static vanilla JS frontend (no build step) that's copied into every day folder. Open any day's `index.html` via a local server to browse conversations.

## Setup

```bash
pip install requests tqdm
```

Place your Snapchat export ZIP(s) in `input/` before running. Multiple ZIPs are supported — the primary export (`mydata~*.zip`) and any numbered continuations (`mydata~*-1.zip`, `-2.zip`, …) are all merged automatically.

## Usage

```bash
# Full run — processes ZIPs, fetches Bitmoji avatars, writes output/
python3 splitter.py

# Skip Bitmoji fetching (faster, uses coloured ghost SVGs as fallbacks)
python3 splitter.py --no-bitmoji
```

Then serve the output directory:

```bash
cd output && python3 -m http.server 8080
```

Open `http://localhost:8080/dashboard.html` for the stats overview, or navigate directly to `http://localhost:8080/days/YYYY-MM-DD/index.html` for any day.

## Output structure

```
output/
├── dashboard.html          ← aggregate stats + activity heatmap
└── days/
    └── YYYY-MM-DD/
        ├── index.html      ← day viewer (copy of web/)
        ├── conversation.js ← embedded JSON for this day
        ├── styles.css
        ├── js/
        ├── media/          ← snaps and chat media for this day
        ├── bitmoji/        ← avatars for users active this day
        └── orphaned/       ← media that couldn't be matched to a message
```

## Project structure

```
splitter.py         ← backend pipeline (single file, ~600 lines)
ghost.svg           ← fallback avatar shape
update_templates.py ← utility: re-copies web/ into existing day folders
                      without re-running the full pipeline
web/
├── index.html      ← day viewer shell + Video.js + custom CSS
├── styles.css      ← Tailwind 3.4 pre-compiled + custom overrides
├── dashboard.html  ← dashboard template (DASHBOARD_DATA placeholder)
└── js/
    ├── main.js         ← entry point, nav wiring, Video.js init
    ├── config.js       ← JSON → UI data structures, per-user colours
    ├── ui.js           ← message bubbles, media rendering, conversation list
    ├── utils.js        ← timestamp parsing, relative time, SVG icons
    ├── audio-player.js ← canvas waveform, Web Audio API, speed control
    └── lightbox.js     ← full-screen media overlay, prev/next nav
```

## Notes

- **Timestamps**: ZIP central-directory `0x5455` extra fields are used to recover real file modification times rather than extraction times.
- **Media matching**: each media file is matched to the nearest message within a 30-second window; a 5-second penalty per already-matched message spreads media across messages when multiple files have similar timestamps.
- **Groups**: conversation IDs containing `-` are treated as group chats.
- **Owner detection**: inferred from the first outgoing (`IsSender: true`) message in the chat history.
- The `output/` and `input/` directories are gitignored — they contain personal data.
