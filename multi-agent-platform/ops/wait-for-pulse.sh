#!/usr/bin/env bash
# Wait until the PM2 user's PulseAudio-compatible socket accepts commands.
set -euo pipefail

timeout_seconds="${PULSE_WAIT_TIMEOUT_SECONDS:-60}"
deadline=$((SECONDS + timeout_seconds))

until pactl info >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "PipeWire/PulseAudio did not become ready within ${timeout_seconds}s" >&2
    exit 1
  fi
  sleep 1
done

echo "PipeWire/PulseAudio is ready"
