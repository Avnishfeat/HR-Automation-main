# Interview Agent Operations

The operational installation, monitoring, recovery, and retention runbook is
kept in [ops/README.md](../ops/README.md). It includes the exact systemd
drop-in required to order PipeWire/Pulse before the PM2 user service and the
safe maintenance-window recovery commands.

The health endpoint is:

```text
GET /api/v1/interview/health/detailed
```

It is suitable for a reverse-proxy monitor and reports audio, disk write,
STT/TTS, LLM, active session/task, webhook-outbox, and local-retention state.
