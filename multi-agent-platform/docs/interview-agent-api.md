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
5. Poll `GET /analysis/{buss_id}` until a terminal result is available.

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
| `X-Idempotency-Key` | HTTP header | No | — | Stable third-party appointment/interview ID used to make retries safe. |

Example:

```bash
curl -X POST "https://<host>/api/v1/interview/start-google-meet" \
  -H "X-Idempotency-Key: third-party-interview-12345" \
  -F "meet_link=https://meet.google.com/abc-defg-hij" \
  -F "job_role=Data Analyst" \
  -F "candidate_email=candidate@example.com" \
  -F "buss_id=BUSS-123" \
  -F "job_description=Analyze data and build business dashboards." \
  -F 'questionnaire_json=["Describe a SQL optimization you made.","How do you validate a dashboard?"]' \
  -F "enable_video=true" \
  -F "resume=@/path/to/candidate-resume.pdf;type=application/pdf"
```

Successful response (`202 Accepted`):

```json
{
  "status": "pending",
  "session_id": "8f2b7b5f-3f1f-49d7-8895-6a98ad3c0a55"
}
```

### Safe Start Retries

When a third-party platform may retry after a timeout or lost response, send a
stable `X-Idempotency-Key` on the original request and every retry. Use its
unique scheduled interview/appointment ID, not `buss_id` unless `buss_id` is
unique per interview.

If the original request was accepted, a retry returns `202 Accepted` with the
same `session_id`, `idempotent_replay: true`, and the
`Idempotent-Replay: true` response header. It does not start another bot.

The PostgreSQL deployment keeps accepted keys for 90 days by default.
Set `IDEMPOTENCY_KEY_RETENTION_DAYS` to change that retention period.

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

`active_or_not_found` means no process-local task/session and no persisted
interview record were found. Use analysis retrieval by `buss_id` for the final
result.

## End an Interview

```http
POST /{session_id}/end
```

Requests a graceful stop. The interview task performs its normal cleanup and
persists its terminal result for analysis retrieval.

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

## Retrieve Interview Analysis

```http
GET /analysis/{buss_id}
```

Actionabl should poll this endpoint with the same globally unique `buss_id`
sent when creating the interview. The platform sends no completion webhooks.

While the interview or analysis is pending, the response is `202 Accepted`:

```json
{
  "buss_id": "BUSS-123",
  "session_id": "8f2b7b5f-3f1f-49d7-8895-6a98ad3c0a55",
  "status": "analyzing",
  "terminal_reason": null,
  "analysis": null,
  "agent_errors": [],
  "completed_at": null,
  "retry_after_seconds": 15
}
```

After a terminal result, the response is `200 OK` and `analysis` contains the
full final report, including transcript and agent errors. A terminal failure
before report generation returns `analysis: null` with its final status,
`terminal_reason`, and agent errors. Unknown IDs return `404`.

### Interrupted interview recovery

Actionabl must treat the following terminal results as requiring a replacement
interview. It creates that replacement with a new globally unique `buss_id` and
retains the original interrupted record as audit history:

| Status | `terminal_reason` | Meaning |
| --- | --- | --- |
| `interrupted` | `backend_shutdown` | The backend performed a controlled shutdown and cancelled an active interview task. |
| `interrupted` | `backend_restarted` | The backend/VM stopped unexpectedly; the next startup recovered the unfinished record. |

The Interview Agent does not automatically rejoin a Meet, send a webhook, or
notify the candidate or operator for either condition.

## Operational Health

```http
GET /health
GET /health/detailed
```

Both routes are under the Interview Agent base URL. The detailed endpoint
returns `503` if PostgreSQL, required services, disk storage, STT/TTS, LLM, or
Linux audio are unhealthy. It also reports active task/session count and local
retention state.

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
does not modify stored transcripts, reports, or database-backed analysis records.

Use `TTS_PRONUNCIATION_OVERRIDES_JSON` to extend the glossary or replace a
default entry. It must be a JSON object of source text to the desired spoken
text; invalid entries are ignored and defaults remain active.

```env
TTS_PRONUNCIATION_OVERRIDES_JSON='{"MERN":"M E R N","Kubernetes":"koo ber net eez"}'
```

Restart PM2 after changing this variable.
