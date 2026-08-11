# Interview operations

These tools are prepared for the `ai` user and do not change live services
until you explicitly run the recovery script or install the supplied systemd
units.

## Boot ordering

This deployment uses the system service `pm2-ai.service`, which runs as `ai`
(UID `1004`). Linger is already enabled for that user. Install the system-unit
drop-in as follows:

```bash
sudo mkdir -p /etc/systemd/system/pm2-ai.service.d
sudo cp ops/systemd/pm2-audio-ordering.conf /etc/systemd/system/pm2-ai.service.d/audio.conf
sudo systemctl daemon-reload
sudo systemctl show pm2-ai.service -p Environment | tr ' ' '\n' | rg 'XDG_RUNTIME_DIR|PULSE_SERVER'
```

The drop-in waits for `pactl info` before PM2 starts. It does not restart PM2
until you explicitly run a maintenance-window restart. Its repository path and
UID are specific to this machine; update both if the project or service user
changes.

Confirm the lingered user's audio units are present before that restart:

```bash
systemctl --user status pipewire.service pipewire-pulse.service wireplumber.service
sudo -u ai XDG_RUNTIME_DIR=/run/user/1004 PULSE_SERVER=unix:/run/user/1004/pulse/native pactl info
```

## Health monitoring

Install the one-minute systemd timer:

```bash
cp ops/interview-monitor.env.example ops/interview-monitor.env
mkdir -p ~/.config/systemd/user
cp ops/systemd/interview-health-monitor.service ~/.config/systemd/user/
cp ops/systemd/interview-health-monitor.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now interview-health-monitor.timer
systemctl --user status interview-health-monitor.timer
```

Failed checks are visible in the user journal and return a non-zero status for
your monitoring system:

```bash
journalctl --user -u interview-health-monitor.service -f
```

## Recovery verification

Run only during a maintenance window; each mode first refuses if the health
endpoint reports an active interview.

```bash
ops/test-interview-recovery.sh database
ops/test-interview-recovery.sh chrome-lock-check
ops/test-interview-recovery.sh pm2
ops/test-interview-recovery.sh audio
```

`pm2` verifies the backend restart, `audio` verifies PipeWire/Pulse recovery,
and `database` verifies that PostgreSQL can be opened and queried. The Chrome
mode does not create or remove a real profile lock; it reports the safe behavior.

## Retention

The backend runs retention at startup and then hourly. Defaults are:

- terminal PostgreSQL interview records: 90 days
- terminal interview session directories: 90 days

Override them with `INTERVIEW_RECORD_RETENTION_DAYS`,
`INTERVIEW_SESSION_RETENTION_DAYS`, and
`LOCAL_RETENTION_CLEANUP_INTERVAL_SECONDS`. Pending and active interviews are
never deleted by this job.
