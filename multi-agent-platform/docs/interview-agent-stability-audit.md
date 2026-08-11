# Interview Agent Stability Audit

## Scope and conclusion

This is a static engineering review of the Interview Agent as currently implemented. It covers request scheduling, session state, Google Meet browser control, Linux audio, orchestration, cleanup, webhook delivery, observability, and test/deployment hygiene. It is not a production load test.

The agent is suitable only for a controlled, single-interview deployment at present. Its configured capacity of five concurrent interviews is not supported by its shared Chrome profile, global audio devices, and singleton orchestration state. The first stabilization goal should be durable, restart-safe execution for one session; concurrency should be reintroduced only after resource isolation is in place.

## Critical findings

### Interview execution is not durable

Interviews run as FastAPI background tasks, with active session state and capacity tracking held in process memory. The state manager has no persistence: it always starts from `saved_data = None` and `save_checkpoint()` is empty. A PM2 restart, VM restart, process crash, or deployment discards active interview progress and any work that has not reached final report delivery.

Evidence: [background task](../app/agents/interview/core/background.py), [state manager](../app/agents/interview/orchestrator/state_manager.py), and [in-memory limiter](../app/agents/interview/core/limiter.py).

**Remediation:** create a durable job record and session state in a database, move long-running work to a worker queue, and persist all terminal statuses and webhook delivery attempts. On worker start, recover or explicitly mark orphaned jobs instead of silently losing them.

### Configured concurrency conflicts with shared browser and audio resources

The limiter permits five active sessions, but every Meet session uses the same persistent `chrome_profile`. Browser startup also removes a `SingletonLock`, which can interfere with an already-running browser. Linux audio routing uses shared Pulse/PipeWire sinks and default sources, so simultaneous sessions can mix playback and recording.

Evidence: [session manager](../app/agents/interview/infrastructure/browser/meet_session_manager.py) and [browser controller](../app/agents/interview/infrastructure/browser/meet_controller.py).

**Remediation:** until isolation exists, enforce a hard limit of one interview per worker. For true concurrency, allocate a unique browser profile, audio namespace/device pair, and runtime/task container per session. Never delete another active browser's lock file.

### Webhook delivery blocks the event loop and is not recoverable

Final delivery invokes synchronous `requests.post` directly from the async interview task. Failed calls sleep synchronously for 30, 60, and 120 seconds; with request timeouts, one failed delivery can occupy the event loop for about 250 seconds. Cleanup proceeds after a failed final webhook, and no durable outbox records pending delivery.

Evidence: [webhook client](../app/utils/webhook_client.py) and [finalization flow](../app/agents/interview/core/background.py).

**Remediation:** use an async client or execute delivery outside the event loop, and store webhook events in an outbox with an idempotency key, attempt count, next-attempt time, and terminal delivery status. Retain report data until delivery succeeds or reaches a visible dead-letter state.

## High-priority findings

### Session state is shared by the singleton orchestrator

The orchestrator stores one `participant_monitor`, while the malpractice handler stores one shared `processing` event. A second interview overwrites the monitor reference from the first; cleanup for one session can stop the wrong monitor, and a violation in one session can suppress violation processing in another.

**Remediation:** make monitor, violation state, integrity task ownership, and cleanup handles part of a per-session runtime object. The singleton orchestrator should contain only stateless dependencies.

Evidence: [orchestrator](../app/agents/interview/orchestrator/meet_interview_orchestrator.py) and [malpractice handler](../app/agents/interview/orchestrator/malpractice_handler.py).

### Shutdown does not drain active interviews

The production lifespan cancels only the audio recovery task. It does not stop or await active interviews, close browser contexts, persist interrupted state, or queue final failure webhooks. The alternate cleanup lifespan is not used by the deployed `app.main` application.

**Remediation:** add a shutdown coordinator: stop accepting new sessions, mark running jobs as draining, await cleanup up to a deadline, then persist or queue an interrupted terminal event for work that remains.

Evidence: [application lifespan](../app/main.py) and [session cleanup](../app/agents/interview/infrastructure/browser/meet_session_manager.py).

### Broad exception handling produces false-success results

Many browser, STT, and orchestration failures are converted to `False`, `[Error]`, `[No response]`, or ignored. The orchestration path catches fatal exceptions and ultimately builds a response with `status: completed`; candidate-presence logic also treats some controller exceptions as present. This can produce a completed report for a failed interview.

**Remediation:** use typed error classes and a finite set of terminal session statuses. Preserve the root failure, distinguish retryable from terminal faults, and report a failure status whenever a required stage cannot complete.

Evidence: [orchestrator](../app/agents/interview/orchestrator/meet_interview_orchestrator.py) and [STT service](../app/agents/interview/services/audio/stt_service.py).

### Audio recovery does not refresh STT device selection

Virtual audio sinks can be recreated after PipeWire/Pulse restarts, but the STT service selects its `sounddevice` input index once during service startup. That index may be stale after a device-server restart. Streaming worker exceptions are broadly swallowed, so the failure is likely to appear as a candidate who gave no response.

**Remediation:** probe audio readiness before every recording, refresh device selection after audio-server recovery, and surface stream errors as structured retryable failures. Bound audio queues and retain explicit stream-health metrics.

### Background work has no ownership or backpressure

Integrity checks are created as untracked tasks at each interview turn. Video capture performs frame analysis synchronously in its loop, and participant-monitor cancellation is not awaited. Slow video/model operations can overlap, continue after session end, or consume the event loop unpredictably.

**Remediation:** maintain a per-session task group, allow only one integrity check at a time, run CPU-bound analysis in a worker thread/process, and cancel plus await every child task during teardown.

Evidence: [orchestrator background tasks](../app/agents/interview/orchestrator/meet_interview_orchestrator.py) and [video capture loop](../app/agents/interview/infrastructure/browser/meet_session_manager.py).

## Operational and security gaps

- The health router is not mounted by `app.main`, leaving no externally exposed readiness check for browser, audio, STT/TTS, active sessions, or webhook backlog.
- The per-session error collector is useful for async task paths but cannot automatically associate logs from manually created threads with a session. Treat `agent_errors` as best-effort until context is propagated explicitly.
- `webhook_url` is an arbitrary server-side request target and callbacks are unsigned. Apply an allowlist or private-network denylist, enforce HTTPS where appropriate, and add an HMAC signature plus idempotency key.
- The API accepts candidate PII while application-level authentication is not enforced and CORS is fully permissive. Put the API behind authenticated ingress and restrict allowed origins.

## Test and deployment hygiene

The repository ignores `tests/`, `ecosystem.config.js`, and deployment-related files. Git currently tracks only `tests/__init__.py`; the visible test suite and PM2 configuration cannot be reconstructed by CI or a fresh clone.

Commit the test suite, dependency lock/configuration, PM2 or systemd unit, and deployment manifests. Add automated scenarios for:

- VM/PM2 restart during each interview phase;
- audio-server restart before and during recording;
- browser launch failure and profile contention;
- concurrent-session admission and resource isolation;
- webhook timeout, retry, duplicate delivery, and recovery after restart;
- graceful shutdown with active browser, audio, and child tasks.

## Stabilization sequence

1. Enforce one session per worker and stop deleting shared Chrome locks.
2. Make final reports and webhook delivery durable through a database-backed job/outbox model.
3. Isolate all session runtime state and implement coordinated shutdown.
4. Replace silent fallbacks with typed errors, deadlines, and truthful terminal statuses.
5. Add browser/audio readiness checks, task ownership, health endpoints, and production monitoring.
6. Commit the currently ignored test and deployment assets, then gate releases on restart, outage, and concurrency tests.
