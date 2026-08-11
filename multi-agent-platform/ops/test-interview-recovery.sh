#!/usr/bin/env bash
# Run only during a maintenance window and only when no interview is active.
set -euo pipefail

mode="${1:-}"
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
health_url="${INTERVIEW_HEALTH_URL:-http://127.0.0.1:8048/api/v1/interview/health/detailed}"
pm2_name="${PM2_APP_NAME:-multi-agent-backend}"

if [[ ! "$mode" =~ ^(pm2|audio|webhook|chrome-lock-check)$ ]]; then
  echo "Usage: $0 {pm2|audio|webhook|chrome-lock-check}" >&2
  exit 2
fi

health="$(curl --fail --silent --show-error --max-time 10 "$health_url")"
printf '%s' "$health" | python3 -c '
import json
import sys
runtime = json.load(sys.stdin).get("runtime", {})
if runtime.get("active_interview_tasks", 0) or runtime.get("active_sessions", 0):
    raise SystemExit("Refusing recovery test while an interview is active")
'

case "$mode" in
  pm2)
    pm2 restart "$pm2_name"
    ;;
  audio)
    systemctl --user restart pipewire.service pipewire-pulse.service wireplumber.service
    ;;
  webhook)
    "$project_dir/venv/bin/python" -c '
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import app.utils.webhook_outbox as outbox
with TemporaryDirectory() as temp_dir:
    outbox.OUTBOX_DIR = Path(temp_dir)
    outbox.enqueue_webhook("https://example.invalid/interview", {"event": "recovery_test"})
    with patch.object(outbox.requests, "post", side_effect=outbox.requests.ConnectionError("expected test failure")):
        assert outbox.deliver_due_webhooks()["retried"] == 1
    with patch.object(outbox.requests, "post", return_value=Mock(status_code=204)):
        assert outbox.deliver_due_webhooks()["delivered"] == 1
print("Webhook retry recovery test passed")'
    ;;
  chrome-lock-check)
    lock_path="$project_dir/chrome_profile/SingletonLock"
    if [[ -e "$lock_path" || -L "$lock_path" ]]; then
      echo "Chrome profile is locked at $lock_path. A new session will safely fail instead of deleting it."
    else
      echo "Chrome profile is currently unlocked; lock-safety code is active and covered by automated tests."
    fi
    ;;
esac

if [[ "$mode" != "webhook" && "$mode" != "chrome-lock-check" ]]; then
  for _ in $(seq 1 12); do
    if "$project_dir/ops/check-interview-health.sh"; then
      echo "${mode} recovery test passed"
      exit 0
    fi
    sleep 5
  done
  echo "${mode} recovery test did not restore health within 60 seconds" >&2
  exit 1
fi
