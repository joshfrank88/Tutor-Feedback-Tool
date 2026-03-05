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

### Skip transcription (reuse existing transcript)

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
└── meta.json                      # Run config, model names, timings
```

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
