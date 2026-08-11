# Interview Agent: Stability Improvements Summary

## One-minute summary

We made the Interview Agent safer to run on a VM and easier to support. The
main focus was reliable audio after a restart, truthful interview outcomes,
reliable final webhooks, and clearer health visibility. We also improved how
the agent speaks technical terms such as **MERN**, **API**, and **SQL**.

The system is now designed for **one interview at a time per worker**. This is
intentional because the browser profile and virtual audio devices are shared.

## What changed, why, and how

| Area | What changed | Why it matters | How it works |
| --- | --- | --- | --- |
| VM restart and audio | PM2 now waits for PipeWire/PulseAudio before starting the backend. | The backend previously started first and could not connect to audio. | The PM2 systemd service has an audio-ordering drop-in and a wait script that checks `pactl` before PM2 restores processes. |
| Audio server restart while backend stays up | Added an audio recovery check. | PipeWire/Pulse can restart independently, leaving the running backend connected to stale audio devices. | Every 15 seconds, and before a new interview/recording, the agent checks and recreates the virtual sinks, Chromium source, and STT recording device when needed. |
| One active interview | Enforced a one-session limit and stopped deleting Chrome's shared lock. | Multiple sessions could mix browser state or audio, and deleting a lock could disturb an active Chrome instance. | The admission limiter allows one session, and Chrome lock files are treated as evidence that a browser is already using that profile. |
| Session shutdown | Added session task ownership and coordinated cleanup. | Background work could continue after an interview ended. | Per-session tasks are registered, cancelled, and awaited during normal completion or shutdown. |
| Honest outcomes | Improved terminal statuses and failure handling. | Some failures could look like a successful completed interview. | Important failures now produce explicit terminal statuses and are recorded as session errors. Candidate departure is no longer treated as a malpractice event. |
| Webhook reliability | Added a local webhook outbox with retries. | A temporary webhook outage should not lose the final result. | The final event is written to disk before delivery. Failed calls are retried in the background and appear in health status. |
| Error visibility | Added a per-session agent-error tracker. | The receiving system needs to know when an interview had technical problems. | Final webhook payloads include `agent_errors` with timestamp, component, error type, and safe message. |
| Health and monitoring | Added basic and detailed health endpoints. | Support needs a quick way to know whether audio, speech services, storage, and delivery are working. | `GET /api/v1/interview/health/detailed` reports component health, active work, outbox counts, and retention status. |
| Storage hygiene | Added retention cleanup and archived the historical session folders. | Old local files can slowly fill disk. | Old delivered/failed outbox files and eligible session data can be cleaned up; historical sessions were preserved in an archive rather than discarded. |
| TTS quality | Moved TTS to Gemini 3.1 Flash TTS and added a pronunciation glossary. | The old voice did not handle some spoken technical language consistently. | Gemini TTS uses the `Kore` voice. The TTS-only glossary says `MERN` as “mern” and spells `API`, `SQL`, etc. The original transcript is not changed. |
| STT quality | Confirmed Google Speech-to-Text V2 `chirp_3` with automatic punctuation. | Interview transcripts need readable sentence structure. | Streaming STT is configured for `en-IN` and automatic punctuation. |

## Simple operational flow

```text
VM starts
  → PipeWire/PulseAudio becomes ready
  → PM2 starts backend
  → Backend checks audio and exposes health
  → One interview is admitted
  → Final report/error event is written to outbox
  → Webhook is delivered or retried safely
```

## How to demonstrate this in a meeting

1. Show the detailed health response:

   ```bash
   curl -s http://127.0.0.1:8048/api/v1/interview/health/detailed
   ```

   Explain that `linux_audio`, `stt_v2`, `tts`, storage, active sessions, and
   webhook-outbox counts are visible in one place.

2. Show the boot proof after a restart:

   ```bash
   sudo journalctl -u pm2-ai -b --no-pager
   ```

   Look for **“PipeWire/PulseAudio is ready”** before PM2 resurrects the
   backend.

3. Explain the failure path: if a final webhook is unavailable, the result is
   retained in the local outbox and retried instead of silently being lost.

4. During a short test interview, use a question containing “MERN stack”,
   “API”, and “SQL” to demonstrate clearer speech.

## Configuration to know

| Setting | Purpose |
| --- | --- |
| `LINUX_AUDIO_RECOVERY_INTERVAL_SECONDS` | Audio health-check interval; default is 15 seconds. |
| `GEMINI_TTS_MODEL` | TTS model; default is `gemini-3.1-flash-tts-preview`. |
| `GEMINI_TTS_VOICE` | TTS voice; default is `Kore`. |
| `TTS_PRONUNCIATION_OVERRIDES_JSON` | Adds or overrides spoken terms without editing code. |

Example pronunciation override:

```env
TTS_PRONUNCIATION_OVERRIDES_JSON='{"Kubernetes":"koo ber net eez"}'
```

Restart `multi-agent-backend` through PM2 after changing TTS settings.

## Current boundaries and next steps

- This is a reliable **single-session** design, not a concurrency solution.
- Active interviews are still not database-backed. A VM/process failure during
  an active interview cannot fully resume that interview; it is handled as a
  controlled interruption.
- The local outbox is durable across backend restarts, but a database-backed
  job/outbox system remains the next step when database ownership is available.
- Monitoring should alert on detailed-health failures, pending/failed webhooks,
  audio errors, and low disk space.

For full operational commands, see [Interview Agent Operations](interview-operations.md).
For endpoint and webhook details, see [Interview Agent API Reference](interview-agent-api.md).
