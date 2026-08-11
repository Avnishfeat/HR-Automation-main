#!/usr/bin/env bash
# Suitable for a systemd timer, cron, or an external monitoring probe.
set -euo pipefail

health_url="${INTERVIEW_HEALTH_URL:-http://127.0.0.1:8048/api/v1/interview/health/detailed}"
max_pending="${INTERVIEW_MAX_PENDING_WEBHOOKS:-10}"
min_free_mb="${INTERVIEW_MIN_FREE_DISK_MB:-1024}"
data_dir="${INTERVIEW_DATA_DIR:-data}"
alert_webhook="${INTERVIEW_HEALTH_ALERT_WEBHOOK:-}"

response="$(curl --fail --silent --show-error --max-time 10 "$health_url")" || {
  message="Interview health endpoint is unavailable: ${health_url}"
  echo "$message" >&2
  response=""
  status=1
}

if [[ -n "${response:-}" ]]; then
  printf '%s' "$response" | python3 -c '
import json
import sys

payload = json.load(sys.stdin)
max_pending = int(sys.argv[1])
errors = []
if payload.get("status") != "healthy":
    errors.append(f"status={payload.get('status')}")
components = payload.get("components", {})
for component in ("linux_audio", "disk_storage", "stt_v2", "tts", "llm_api"):
    value = components.get(component)
    if component == "disk_storage":
        healthy = value == "writable"
    else:
        healthy = value == "operational"
    if not healthy:
        errors.append(f"{component}={value}")
outbox = payload.get("runtime", {}).get("webhook_outbox", {})
if outbox.get("failed", 0) > 0:
    errors.append(f"failed_webhooks={outbox['failed']}")
if outbox.get("pending", 0) > max_pending:
    errors.append(f"pending_webhooks={outbox['pending']}")
if errors:
    print("Interview health alert: " + ", ".join(errors), file=sys.stderr)
    raise SystemExit(1)
print("Interview health is healthy")
' "$max_pending" || status=1
fi

available_kb="$(df -Pk "$data_dir" | awk 'NR==2 {print $4}')"
if [[ -z "$available_kb" || "$available_kb" -lt $((min_free_mb * 1024)) ]]; then
  echo "Interview health alert: free disk below ${min_free_mb} MB for ${data_dir}" >&2
  status=1
fi

if [[ "${status:-0}" -ne 0 && -n "$alert_webhook" ]]; then
  message="Interview health check failed on $(hostname) at $(date --iso-8601=seconds)"
  curl --silent --show-error --max-time 10 --fail \
    -H 'Content-Type: application/json' \
    -d "{\"event\":\"interview_health_alert\",\"message\":\"${message}\"}" \
    "$alert_webhook" || true
fi

exit "${status:-0}"
