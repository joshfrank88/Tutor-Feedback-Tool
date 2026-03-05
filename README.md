# Tutor Feedback Pipeline

A local-first CLI + web tool that turns tutoring session recordings into
platform-specific feedback. Transcribe locally with
[faster-whisper](https://github.com/SYSTRAN/faster-whisper), extract structured
session data with Claude, and render tailored feedback for different tutoring
platforms — in your voice, not AI's.

## Why faster-whisper?

This project uses **faster-whisper** instead of openai-whisper because it is
4–8× faster, uses ~50% less memory, and produces equivalent accuracy. It runs
entirely offline after the initial model download, and works well on macOS with
CPU-only inference (INT8 quantisation via CTranslate2).

## Prerequisites

### Homebrew packages

```bash
brew install ffmpeg python@3.11
```

### Anthropic API key

Sign up at <https://console.anthropic.com> and create an API key.

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Or create a `.env` file (see `.env.example`):

```bash
cp .env.example .env
# Edit .env and paste your key
```

## Installation

### Option A – uv (recommended)

```bash
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[dev]"
```

### Option B – pip + venv

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
```

### Whisper model download

The first transcription will download the Whisper model (~150 MB for `base`).
This happens automatically and only once — subsequent runs use the cached model.

You can change the model size via `WHISPER_MODEL` in your `.env`:

| Model      | Size    | Speed   | Accuracy |
|------------|---------|---------|----------|
| `tiny`     | ~75 MB  | Fastest | Lower    |
| `base`     | ~150 MB | Fast    | Good     |
| `small`    | ~500 MB | Medium  | Better   |
| `medium`   | ~1.5 GB | Slow    | High     |
| `large-v3` | ~3 GB  | Slowest | Highest  |

## Usage

### Web UI

The easiest way to use the pipeline is through the web interface:

```bash
tutor-feedback serve
```

This opens a browser at `http://127.0.0.1:8000` where you can:
- Drag-and-drop a recording file
- Enter the student name and pick platforms
- Watch real-time pipeline progress
- View, copy, and browse all generated feedback
- Access past sessions from the History tab

Options: `--port 9000`, `--host 0.0.0.0`, `--no-open` (skip auto-opening browser).

### CLI: Run the full pipeline

```bash
tutor-feedback run /path/to/recording.m4a \
  --student "Andy" \
  --platform intergreat \
  --platform politicsexplained \
  --platform simpletext
```

### Paste mode (notes / transcript)

Generate feedback from **pasted** notes or transcript text (e.g. from Granola). Same two-stage pipeline: EXTRACT → RENDER. No recording or Whisper.

**From clipboard (macOS):**
```bash
pbpaste | tutor-feedback paste --student "Andy" --platform humanities --platform intergreat --platform private --open
```

**With inline text:**
```bash
tutor-feedback paste --student "Andy" --text "Session with Andy. Covered algebra. He understood quadratics. Homework: ex 1-4." --platform humanities --platform intergreat --platform private --open
```

**Options:**
- `--student` — Student name (default: Unknown).
- `--platform` — Repeat for each format. Default: **humanities**, **intergreat**, **private**. Optional: **keystone-quick**.
- `--text` — Paste text directly; if omitted, reads from STDIN.
- `--source` — Label stored in metadata (default: granola).
- `--meeting-source` — Optional (e.g. zoom, gmeet); metadata only, not shown in feedback.
- `--open` — Open the session folder in Finder when done.

On success, a macOS notification appears: *Tutor Feedback Ready • &lt;student&gt; • &lt;platforms&gt; • click to open folder*.

**Outputs** (same session folder layout as `run`): `input_raw.txt`, `notes.txt` and/or `transcript.txt`, `extracted.json`, `feedback_humanities_explained.txt`, `feedback_intergreat.txt`, `feedback_private.txt`, `feedback_keystone_quick.txt` (if requested), `homework.txt`, `meta.json`, `result.json` (trigger=`paste`).

**Phase 2:** Granola MCP will be added as an alternative input adapter; swapping the input source will stay trivial (paste vs MCP).

```bash
tutor-feedback run /path/to/recording.m4a \
  --student "Andy" \
  --platform intergreat \
  --transcript ./data/sessions/2025-06-15__Andy__140000/transcript.json
```

### Dry run (create folder structure only)

```bash
tutor-feedback run /path/to/recording.m4a \
  --student "Andy" \
  --platform intergreat \
  --dry-run
```

### List available style cards

```bash
tutor-feedback list-styles
```

### Validate session outputs

```bash
tutor-feedback validate ./data/sessions/2025-06-15__Andy__140000/
```

### Open session folder in Finder after pipeline

```bash
tutor-feedback run recording.m4a --student "Andy" --platform simpletext --open
```

### Run as a Python module

```bash
python -m tutor_feedback run recording.m4a --student "Andy" --platform intergreat
```

## Output structure

Each run creates a session folder under `./data/sessions/`:

```
data/sessions/2025-06-15__Andy__140000/
├── audio.wav                      # Converted mono 16 kHz WAV
├── transcript.txt                 # Plain text with timestamps
├── transcript.json                # Segments [{start, end, text}, ...]
├── extracted.json                 # Structured session data
├── feedback_intergreat.txt        # Field-based feedback for Intergreat
├── feedback_politicsexplained.txt # Short narrative (100-200 words)
├── feedback_simpletext.txt        # WhatsApp message (2-3 sentences)
├── homework.txt                   # Consolidated homework view
├── meta.json                      # Run config, model names, timings
└── result.json                    # Machine-readable result for n8n/scripts
```

When a run is triggered by **watch** or **webhook**, the same outputs are produced. Failed jobs write `data/dead_letter/<job_id>/error.json` with a user-friendly message and stack trace.

## Style cards / Platforms

Platform-specific formatting is driven by YAML style cards in `./styles/`.
Each card controls tone, word limit, format, and do/don't rules.

Three platforms are included:

- **intergreat** – structured fields (session summary, topics, progress,
  areas for development, homework, next focus, notes). Output is labelled
  sections you can copy into Intergreat's form fields.
- **politicsexplained** – single text box, 100–200 word narrative paragraph.
- **simpletext** – WhatsApp message to clients, 2–3 sentences max.

Create your own by adding a new `.yaml` file to `./styles/`.

## Voice matching (making output sound like you)

The pipeline uses your real past feedback as few-shot examples so the output
matches your writing style, not generic AI text. This is the single most
important thing you can do to get good results.

### Adding examples

Drop `.txt` files into `styles/<platform>/examples/`:

```
styles/
├── intergreat/
│   └── examples/
│       ├── 01.txt    ← a real Intergreat feedback you wrote
│       ├── 02.txt
│       └── 03.txt
├── politicsexplained/
│   └── examples/
│       ├── 01.txt    ← a real PE feedback you wrote
│       └── 02.txt
└── simpletext/
    └── examples/
        ├── 01.txt    ← a real WhatsApp message you sent
        └── 02.txt
```

Or use the CLI:

```bash
# From a file
tutor-feedback add-example intergreat ~/Desktop/old_feedback.txt

# Paste interactively (Ctrl+D to finish)
tutor-feedback add-example simpletext
```

**How many?** 3–5 examples per platform is the sweet spot. More is fine but
has diminishing returns.

**What makes a good example?** Any real feedback you've actually sent.
Don't curate or polish it — the messier and more "you" it is, the better
the voice matching works.

### What happens under the hood

When examples exist for a platform, the render prompt:

1. Shows all your examples to Claude with instructions to study your
   sentence length, vocabulary, rhythm, punctuation habits, and
   how you open/close
2. Tells Claude to reproduce your voice exactly — not improve it
3. Applies a strict banned-word list (no "delved into", "showcased",
   "demonstrated a strong understanding", etc.) to kill common AI tells
4. Bans structural AI patterns (triple adjectives, "While X, Y"
   transitions, generic motivational closings)

Check how many examples are loaded:

```bash
tutor-feedback list-styles
```

## Automation (Local)

You can run the pipeline automatically when you drop a recording into a folder. **Requirement:** `brew install ffmpeg` (see Prerequisites).

### Folder watch

```bash
tutor-feedback watch ./recordings/inbox \
  --student-from-filename \
  --platform keystone \
  --platform private
```

- **Accepted file types:** `.m4a`, `.mp3`, `.wav`, `.mp4`, `.mov`. When a new file appears, the tool waits until the file is **stable** (size unchanged for 10 seconds) so uploads/copies can finish, then runs the pipeline.
- **Outputs:** Each run creates a new session folder under `./data/sessions/` (same as `tutor-feedback run`) and writes a machine-readable **`result.json`** in that folder.
- **processed/ and failed/:** On success, the original recording is moved to `<folder>/processed/`. On failure, it is moved to `<folder>/failed/` and an **`error_<filename>.json`** file is written next to it with `job_id` and `error` (e.g. `error_Andy_2026-03-05.m4a.json`).
- **Idempotency:** Jobs are keyed by file fingerprint (size + mtime + sha256). If the same file was already processed successfully, the tool returns the existing result and does **not** reprocess unless you pass **`--force`**.
- **Options:**
  - `--student-from-filename`: derive student name from filename (e.g. `Andy_2026-03-05.m4a` → Andy; fallback **Unknown** if not parseable).
  - `--student "Name"`: default student when not using `--student-from-filename`.
  - `--platform`: repeat for multiple platforms; **default is `["private"]`** if none passed (use a style name that exists in `./styles/`, e.g. `intergreat`, `simpletext`).
  - `--move` / `--no-move`: move files to processed/ or failed/ (default: move).
  - `--stable-seconds 10`: seconds to wait for file size to be stable (default: 10).
  - `--force`: reprocess even if the same file was already processed.

Press **Ctrl+C** for clean shutdown.

### Automation (Webhook + n8n)

The webhook server lets n8n, Zapier, or scripts trigger jobs and poll for results.

**Set secret (optional):** `export TUTOR_FEEDBACK_WEBHOOK_SECRET="your-secret"`. If set, require header `X-TUTOR-FEEDBACK-SECRET` or return 401.

**Run server:** `tutor-feedback webhook-serve --host 127.0.0.1 --port 8787`

**Trigger (local path):**
```bash
curl -X POST http://127.0.0.1:8787/trigger -H "Content-Type: application/json" \
  -H "X-TUTOR-FEEDBACK-SECRET: your-secret" \
  -d '{"recording_path":"/path/to/rec.m4a","student":"Andy","platforms":["intergreat","simpletext"]}'
```
Response: `{"job_id":"...","status":"queued"}` or `"succeeded"` with `already_processed: true` if idempotent.

**Trigger (recording_url):** Server downloads to `./data/inbox/` (max 500 MB, 120 s). Allowed: .m4a .mp3 .wav .mp4 .mov.

**Poll:** `GET /jobs/{job_id}` with same secret header. Returns `job_id`, `status`, `retries`, `error`, `result` (Result schema when succeeded), `session_path`.

**Import n8n workflow:** Import `automations/n8n/TutorFeedbackWebhookWorkflow.json`. See **automations/n8n/README.md** for setup and where result.json is stored.

### result.json (machine-readable output)

Each session folder includes `result.json` with:

- `session_id`, `student`, `created_at_iso`, `trigger` (`watch` | `cli` | etc.)
- `input_recording`: `original_path`, `processed_path` (null until moved), `sha256`, `size_bytes`, `mtime`
- `outputs`: `session_folder`, `transcript_txt`, `transcript_json`, `extracted_json`, `homework_txt`, `feedback` (per-platform `path` and `text_preview` up to 240 chars)
- `timings_ms`: `transcribe`, `extract`, `render`, `total` (milliseconds)

Paths in `result.json` are absolute. Use this in n8n, Zapier, or scripts to pass results to Notion, Google Docs, email, etc.

### n8n workflow

A ready-to-import workflow is in `automations/n8n/`:

1. Import `automations/n8n/TutorFeedbackWebhookWorkflow.json` in n8n.
2. Start the webhook server: `tutor-feedback webhook-serve --port 8787`.
3. Trigger the workflow’s Webhook node with the same JSON as above. The workflow calls `/trigger`, waits, then polls `/jobs/{id}` and can hand off to Notion/Email (stub nodes; enable and configure as needed).

See **automations/n8n/README.md** for local n8n setup and optional shared secret.

### Idempotency and reliability

- **Same file twice:** Jobs are keyed by file fingerprint (size + mtime + sha256). If the same recording was already processed successfully, the pipeline returns the existing session and does not re-run unless you pass **`--force`** (watch) or `force: true` in metadata (webhook).
- **Failed jobs:** Errors are written to `data/dead_letter/<job_id>/error.json` (webhook). With folder watch, the source file is moved to `folder/failed/` and **`error_<filename>.json`** is written next to it with `job_id` and `error`.
- **Logging:** Use `--verbose` on `watch` and `webhook-serve` for debug logs.

## Running tests

```bash
pytest
```

## Troubleshooting

### `ffmpeg not found`

Install via Homebrew:

```bash
brew install ffmpeg
```

### `faster-whisper` install fails

On Apple Silicon Macs, ensure you're using a native ARM Python (not Rosetta):

```bash
python3 -c "import platform; print(platform.machine())"
# Should print: arm64
```

If you see `x86_64`, install Python via Homebrew:

```bash
brew install python@3.11
```

### `ANTHROPIC_API_KEY is not set`

Either export the variable or add it to `.env`:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

### Whisper model download hangs

The model downloads from Hugging Face on first run. If your network is slow,
try the smaller `tiny` model:

```bash
WHISPER_MODEL=tiny tutor-feedback run recording.m4a --student "Andy" --platform intergreat
```

### Out of memory during transcription

Use a smaller Whisper model (`tiny` or `base`) or close other applications.

### Claude API errors (rate limits, timeouts)

The pipeline retries failed Claude calls up to 2 times. If errors persist,
check your API key and usage limits at <https://console.anthropic.com>.

### Webhook returns 401

You set `TUTOR_FEEDBACK_WEBHOOK_SECRET`; send the same value in the `X-TUTOR-FEEDBACK-SECRET` header.

### Watch or webhook job stays queued or fails

Ensure `ANTHROPIC_API_KEY` is set and ffmpeg is on PATH. Check the terminal where `webhook-serve` or `watch` is running for the error. Failed jobs are recorded in `data/dead_letter/<job_id>/error.json`.

---

## How to run (quick reference)

```bash
# Install
brew install ffmpeg
cd /path/to/tutor-feedback-pipeline
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # add ANTHROPIC_API_KEY

# Manual run
tutor-feedback run /path/to/recording.m4a --student "Andy" --platform intergreat --platform simpletext

# Web UI
tutor-feedback serve

# Folder watch
tutor-feedback watch ./recordings/inbox --student-from-filename --platform intergreat --platform simpletext

# Webhook server
tutor-feedback webhook-serve --port 8787

# Trigger job then get result
curl -X POST http://127.0.0.1:8787/trigger -H "Content-Type: application/json" \
  -d '{"recording_path":"/full/path/to/rec.m4a","student":"Andy","platforms":["intergreat","simpletext"]}'
curl http://127.0.0.1:8787/jobs/<job_id>

# n8n: Import automations/n8n/TutorFeedbackWebhookWorkflow.json; run webhook-serve on 8787; trigger Webhook node with same JSON.
```
