# n8n + Tutor Feedback Pipeline

Importable workflow that triggers the tutor-feedback pipeline via webhook, polls for completion, and (optionally) hands results to Notion or Email.

## Prerequisites

- **tutor-feedback** installed with `ANTHROPIC_API_KEY` set (see project README).
- **n8n** running locally (see below).
- **Webhook server** running: `tutor-feedback webhook-serve --port 8787`

## Running n8n locally (macOS)

```bash
npm install -g n8n
# or: brew install n8n
n8n start
```

Open http://localhost:5678.

## Secret auth (recommended)

Set the same secret on the server and in n8n so requests are authenticated:

```bash
export TUTOR_FEEDBACK_WEBHOOK_SECRET="your-secret-string"
tutor-feedback webhook-serve --port 8787
```

In n8n: **Settings → Variables** → add `TUTOR_FEEDBACK_WEBHOOK_SECRET` = same value. The workflow sends it in the `X-TUTOR-FEEDBACK-SECRET` header.

## Import the workflow

1. In n8n: **Workflows → Import from File** (or paste JSON).
2. Select `TutorFeedbackWebhookWorkflow.json` from this folder.
3. Open the **Webhook** node and note the **Production URL** (or Test URL for local).
4. Ensure **POST /trigger** and **GET job status** nodes point to your webhook server:
   - Default: `http://127.0.0.1:8787`
   - If n8n runs in Docker: `http://host.docker.internal:8787`

## Workflow behaviour

| Node | Purpose |
|------|--------|
| Webhook | Receives POST with `recording_path` or `recording_url`, `student`, `platforms` (default `["private"]`), optional `force`, `metadata`. |
| POST /trigger | Calls `http://127.0.0.1:8787/trigger` with JSON body and optional secret header. |
| Wait 5s | Poll interval. Increase for long recordings. |
| GET job status | Fetches `http://127.0.0.1:8787/jobs/<job_id>`. Returns `job_id`, `status`, `retries`, `error`, `result` (full Result schema). |
| IF status done | If `status` is `succeeded` or `failed`, exit loop; else loop back to Wait. |
| Result (result.json) | Holds `result` (Result schema) and `session_path`. Add a **Write to file** node to save `result.json` (e.g. to a folder you choose). |
| Respond to Webhook | Sends final `job_id`, `status`, `error` back to the webhook caller. |
| Notion / Email | Stubs – enable and add credentials; map `result.outputs.feedback.<platform>.text_preview` or `session_path`. |

## Where result.json is stored

- On the **server**: each run writes to `./data/sessions/<date>__<student>__<time>/result.json` (see project README).
- In **n8n**: the workflow exposes the same content in the **Result (result.json)** node output as `result`. Add a **Write to file** or **Write Binary File** node and save `result` (as JSON) to a path you choose (e.g. `~/exports/result_{{ $json.job_id }}.json`).

## Triggering a job

**From n8n (Webhook node):**  
POST to the Webhook node URL with JSON body:

```json
{
  "recording_path": "/absolute/path/to/recording.m4a",
  "student": "Andy",
  "platforms": ["intergreat", "simpletext"]
}
```

Or with a downloadable URL:

```json
{
  "recording_url": "https://example.com/recording.m4a",
  "student": "Andy",
  "platforms": ["private"]
}
```

**From shell (no n8n):**

```bash
curl -X POST http://127.0.0.1:8787/trigger \
  -H "Content-Type: application/json" \
  -H "X-TUTOR-FEEDBACK-SECRET: your-secret" \
  -d '{"recording_path":"/path/to/rec.m4a","student":"Andy","platforms":["intergreat","simpletext"]}'

curl http://127.0.0.1:8787/jobs/<job_id> \
  -H "X-TUTOR-FEEDBACK-SECRET: your-secret"
```

## Idempotency

If the same file (by fingerprint: size + mtime + sha256) was already processed successfully and `force` is not set, the server returns immediately with `status: "succeeded"` and `already_processed: true` and the existing `session_id` / `session_path`. No pipeline run is performed.

## Troubleshooting

- **Connection refused to 127.0.0.1:8787** – Start the webhook server: `tutor-feedback webhook-serve --port 8787`.
- **401 Unauthorized** – Set `TUTOR_FEEDBACK_WEBHOOK_SECRET` and send the same value in the `X-TUTOR-FEEDBACK-SECRET` header.
- **Job stays queued** – Check the terminal where `webhook-serve` is running (e.g. missing API key, ffmpeg, or invalid path).
- **Long recordings** – Increase the **Wait** node (e.g. 15–30 s) or add a max loop count to avoid infinite polling.
