# Interview Agent API Reference

## Base URL

All Interview Agent routes are under:

```text
https://<host>/api/v1/interview
```

The API currently does not enforce an application-level authentication scheme.
Deploy it behind an authenticated gateway or reverse proxy before exposing it
outside a trusted network.

## Workflow

1. Create an interview with `POST /start-google-meet`.
2. Store the returned `session_id`.
3. Poll `GET /{session_id}/status` while the session runs.
4. Optionally request termination with `POST /{session_id}/end`.
5. Receive the final result and any agent errors at `webhook_url`.

## Start a Google Meet Interview

```http
POST /start-google-meet
Content-Type: multipart/form-data
```

Creates the interview state and schedules the Google Meet bot in the
background. The request returns immediately; it does not wait for the bot to
join or for the interview to finish.

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `meet_link` | string | Yes | — | Google Meet URL for the interview. |
| `job_role` | string | Yes | — | Role being assessed. |
| `resume` | file | Yes | — | Candidate resume: `.pdf`, `.docx`, or `.txt`. |
| `candidate_email` | string | Yes | — | Candidate email included in the final analysis. |
| `buss_id` | string | Yes | — | Business identifier included in the final analysis. |
| `questionnaire_json` | string | No | `null` | JSON array of question strings. |
| `audio_device` | integer | No | `null` | Audio-device index when an explicit device is needed. |
| `enable_video` | boolean | No | `true` | Enables candidate video capture and integrity checks. |
| `job_description` | string | No | `null` | Job-description context for interview generation. |
| `video_capture_method` | string | No | `javascript` | Candidate-video capture method. |
| `webhook_url` | string | No | `null` | Callback endpoint for final interview delivery. |

Example:

```bash
curl -X POST "https://<host>/api/v1/interview/start-google-meet" \
  -F "meet_link=https://meet.google.com/abc-defg-hij" \
  -F "job_role=Data Analyst" \
  -F "candidate_email=candidate@example.com" \
  -F "buss_id=BUSS-123" \
  -F "job_description=Analyze data and build business dashboards." \
  -F 'questionnaire_json=["Describe a SQL optimization you made.","How do you validate a dashboard?"]' \
  -F "enable_video=true" \
  -F "webhook_url=https://client.example.com/webhooks/interview" \
  -F "resume=@/path/to/candidate-resume.pdf;type=application/pdf"
```

Successful response (`202 Accepted`):

```json
{
  "status": "pending",
  "session_id": "8f2b7b5f-3f1f-49d7-8895-6a98ad3c0a55"
}
```

Errors:

| Status | Meaning |
| --- | --- |
| `400` | Resume validation or questionnaire parsing failed. |
| `422` | A required form field is absent or has an invalid type. |
| `503` | The interview concurrency limit was reached. Retry after the supplied `Retry-After` interval. |
| `500` | The interview task could not be scheduled. |

The creation route is rate-limited to two requests per minute per client IP.

## Get Interview Status

```http
GET /{session_id}/status
```

Example:

```bash
curl "https://<host>/api/v1/interview/8f2b7b5f-3f1f-49d7-8895-6a98ad3c0a55/status"
```

Responses:

```json
{
  "status": "active",
  "session_id": "8f2b7b5f-3f1f-49d7-8895-6a98ad3c0a55"
}
```

```json
{
  "status": "completed",
  "session_id": "8f2b7b5f-3f1f-49d7-8895-6a98ad3c0a55"
}
```

`active_or_not_found` means no process-local task/session and no file-backed
terminal status were found. Terminal statuses are retained in the session data
directory; the webhook remains the authoritative final delivery.

## End an Interview

```http
POST /{session_id}/end
```

Requests a graceful stop. The interview task performs its normal cleanup and
will send its final webhook payload if one was configured.

Example:

```bash
curl -X POST "https://<host>/api/v1/interview/8f2b7b5f-3f1f-49d7-8895-6a98ad3c0a55/end"
```

Response:

```json
{
  "status": "ending",
  "session_id": "8f2b7b5f-3f1f-49d7-8895-6a98ad3c0a55"
}
```

Errors: `404` when the session is not active, `503` when the session manager is
unavailable, or `500` for an unexpected termination error.

## Webhook Delivery

Final webhooks are first written to the local `data/webhook_outbox` before any
network request. A background delivery worker sends due events without blocking
the interview task. It retries non-2xx responses and request failures after
30, 60, and 120 seconds (four total attempts). Delivered and exhausted events
remain on disk for operational inspection; monitor the health endpoint below.

Consumers should accept duplicate delivery for the same `session_id` and
`event`, respond with a `2xx` promptly, and process the payload
asynchronously.

### Completed analysis

```json
{
  "event": "analysis_completed",
  "session_id": "8f2b7b5f-3f1f-49d7-8895-6a98ad3c0a55",
  "transcript_path": "data/8f2b7b5f-3f1f-49d7-8895-6a98ad3c0a55/transcript.txt",
  "analysis": "{...serialized final report...}",
  "agent_errors": []
}
```

`analysis` is a JSON-encoded string. Parse it before reading report fields. For
dict-based reports, `metadata.agent_errors` and
`metadata.agent_error_count` repeat the error information.

### Ended before analysis

If the bot cannot join, the candidate does not join, or the task fails before
analysis, the final payload is:

```json
{
  "event": "interview_completed",
  "session_id": "8f2b7b5f-3f1f-49d7-8895-6a98ad3c0a55",
  "status": "error_join_failed",
  "agent_errors": [
    {
      "timestamp": "2026-08-10T12:00:00+00:00",
      "component": "meet_session",
      "type": "BotJoinError",
      "message": "Bot join failed"
    }
  ]
}
```

Each `agent_errors` item has a UTC timestamp, component, type, and message.
Messages are limited to 2,000 characters; stack traces are excluded.

Possible error statuses are `error_capacity_reached`, `error_join_failed`,
`error_candidate_no_show`, and `error_fatal_task`.

## Operational Health

```http
GET /health
GET /health/detailed
```

Both routes are under the Interview Agent base URL. The detailed endpoint
returns `503` if required services, disk storage, STT/TTS, LLM, or Linux audio
are unhealthy. It also reports the active task/session count and webhook
outbox counts (`pending`, `delivered`, and `failed`).

The deployment is deliberately limited to one concurrent interview by default
(`MAX_CONCURRENT_INTERVIEWS=1`), because Chrome's persistent profile and the
virtual audio routing are process-wide resources. Run one application worker
per VM until browser profiles and audio devices are made session-isolated.

## TTS Model

The interview agent uses `gemini-3.1-flash-tts-preview` through Cloud
Text-to-Speech, with the `Kore` prebuilt voice and `en-IN` locale by default.
Set `GEMINI_TTS_MODEL` or `GEMINI_TTS_VOICE` only when changing the configured
model or voice. The service account requires Cloud Text-to-Speech access and
the `aiplatform.endpoints.predict` permission for Gemini-TTS.

### TTS Pronunciation Glossary

Before synthesis, the agent applies a TTS-only glossary. It pronounces stack
names such as `MERN`, `MEAN`, `PERN`, `LAMP`, and `JAMstack` as words, and
spells `API`, `AWS`, `SQL`, `HTML`, `CSS`, and `CI/CD` letter by letter. This
does not modify stored transcripts, reports, or webhook payloads.

Use `TTS_PRONUNCIATION_OVERRIDES_JSON` to extend the glossary or replace a
default entry. It must be a JSON object of source text to the desired spoken
text; invalid entries are ignored and defaults remain active.

```env
TTS_PRONUNCIATION_OVERRIDES_JSON='{"MERN":"M E R N","Kubernetes":"koo ber net eez"}'
```

Restart PM2 after changing this variable.
