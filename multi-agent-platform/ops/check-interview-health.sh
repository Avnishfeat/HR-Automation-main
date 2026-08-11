#!/usr/bin/env bash
# Suitable for a systemd timer, cron, or an external monitoring probe.
set -euo pipefail

health_url="${INTERVIEW_HEALTH_URL:-http://127.0.0.1:8048/api/v1/interview/health/detailed}"
min_free_mb="${INTERVIEW_MIN_FREE_DISK_MB:-1024}"
data_dir="${INTERVIEW_DATA_DIR:-data}"

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
errors = []
if payload.get("status") != "healthy":
    errors.append(f"status={payload.get('status')}")
components = payload.get("components", {})
for component in ("linux_audio", "disk_storage", "stt_v2", "tts", "llm_api", "postgresql"):
    value = components.get(component)
    if component == "disk_storage":
        healthy = value == "writable"
    else:
        healthy = value == "operational"
    if not healthy:
        errors.append(f"{component}={value}")
if errors:
    print("Interview health alert: " + ", ".join(errors), file=sys.stderr)
    raise SystemExit(1)
print("Interview health is healthy")
' || status=1
fi

available_kb="$(df -Pk "$data_dir" | awk 'NR==2 {print $4}')"
if [[ -z "$available_kb" || "$available_kb" -lt $((min_free_mb * 1024)) ]]; then
  echo "Interview health alert: free disk below ${min_free_mb} MB for ${data_dir}" >&2
  status=1
fi

exit "${status:-0}"
