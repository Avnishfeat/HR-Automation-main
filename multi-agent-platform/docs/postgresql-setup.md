# Local PostgreSQL Setup for Interview Retrieval

The Interview Agent requires PostgreSQL 16+ and will not start until
`DATABASE_URL` is configured and the migration has been applied.

## Create the local database

Run these commands on the VM. They create an unprivileged PostgreSQL role for
the Linux user `ai` and an empty database; they do not modify other databases.

```bash
sudo pg_ctlcluster 16 main start
sudo -u postgres createuser --login --no-superuser --no-createdb --no-createrole ai
sudo -u postgres createdb --owner=ai hr_automation_interview
```

If the role or database already exists, skip the corresponding command.

## Configure and migrate

Add this to `.env`. Adjust the port if `pg_lsclusters` reports a different one.

```env
DATABASE_URL=postgresql+asyncpg://ai@/hr_automation_interview?host=/var/run/postgresql&port=5433
DATABASE_CONNECT_TIMEOUT_SEC=5
IDEMPOTENCY_KEY_RETENTION_DAYS=90
INTERVIEW_RECORD_RETENTION_DAYS=90
INTERVIEW_SESSION_RETENTION_DAYS=90
```

Run the migration before restarting PM2:

```bash
venv/bin/alembic upgrade head
pm2 restart multi-agent-backend
```

## Verify

```bash
curl -s http://127.0.0.1:8048/api/v1/interview/health/detailed
```

The response must report `components.postgresql` as `operational`. Actionabl
can then poll:

```text
GET /api/v1/interview/analysis/{buss_id}
```

The endpoint includes candidate information and the full transcript. Keep it
private or restrict it to Actionabl's IP addresses at the reverse proxy.

## Run the integration tests

The PostgreSQL integration suite is deliberately disabled unless a separate
test database is named by `TEST_DATABASE_URL`. It refuses any URL whose
database name does not contain `test`, so it cannot clean the production
database by accident.

Create the one-time test database:

```bash
sudo -u postgres createdb --owner=ai hr_automation_interview_test
```

Then run the suite from the project directory:

```bash
export TEST_DATABASE_URL='postgresql+asyncpg://ai@/hr_automation_interview_test?host=/var/run/postgresql&port=5433'
venv/bin/pytest -q tests/integration/test_interview_persistence.py
```

The test setup recreates only the schema in `hr_automation_interview_test`.
It never uses `DATABASE_URL` or modifies `hr_automation_interview`.
