# Upvote Monitor

Upvote Monitor is a local review and archival application for media discovered
from configured sources.

## Supported deployment

Run exactly one application process and one Uvicorn worker against its SQLite
database. The scheduler and background jobs run inside that process and use
SQLite leases for crash recovery; multiple application processes, multiple
Uvicorn workers, and distributed job runners are not supported. Keep the API on
the local machine or a trusted local network: it does not provide API
authentication and is not intended to be exposed directly to the internet.

The container expects durable mounts at `/data` (application database and
preview cache) and `/download` (approved archives). A typical local `.env` has
host paths for both mounts and an encryption key:

```dotenv
DATA_DIR=/absolute/path/to/upvote-monitor-data
DOWNLOAD_DIR=/absolute/path/to/upvote-monitor-downloads
UPVOTE_MONITOR_SECRET_KEY=replace-with-a-stable-local-secret
```

Start the single supported process with:

```console
docker compose -f docker/docker-compose-dev.yml up --build -d
```

Versioned release images are published for `linux/amd64` at
`ghcr.io/rodolfofigueroa/upvote-monitor`. Pull a fixed release for reproducible
deployments, or `latest` for the newest stable release:

```console
docker pull ghcr.io/rodolfofigueroa/upvote-monitor:1.0.0
docker pull ghcr.io/rodolfofigueroa/upvote-monitor:latest
```

Do not lose or rotate `UPVOTE_MONITOR_SECRET_KEY` while encrypted source
credentials are still needed. Credentials are encrypted in SQLite and are never
returned by the API.

## Database reset and migrations

The current Alembic revision is the migration baseline. An empty data directory
is migrated and seeded automatically on first startup. Every later startup runs
all migrations from the recorded `alembic_version` to the current revision;
operator-initiated schema commands are normally unnecessary.

Unversioned alpha databases made before this baseline are deliberately not
migrated. Startup stops with `Unversioned alpha database found` and leaves the
file unchanged. Perform this one-time reset while the application is stopped,
preserving the old database and any SQLite sidecars as a backup:

```console
docker compose -f docker/docker-compose-dev.yml down
mkdir -p "${DATA_DIR}/alpha-reset-backup"
mv "${DATA_DIR}"/upvote_monitor.db* "${DATA_DIR}/alpha-reset-backup/"
docker compose -f docker/docker-compose-dev.yml up --build -d
```

Set `DATA_DIR` to the same absolute host directory used by Compose before
running those commands. Confirm the glob matches only the old
`upvote_monitor.db`, `upvote_monitor.db-wal`, and `upvote_monitor.db-shm` files.
The old alpha state is not imported into the new database.

For diagnosis, the version recorded by a running container can be inspected
without changing it:

```console
docker compose -f docker/docker-compose-dev.yml exec app \
  uv run python -c 'import sqlite3; print(sqlite3.connect("/data/upvote_monitor.db").execute("select version_num from alembic_version").fetchone()[0])'
```

## Durable workflow and recovery

Approval choices remain editable while an archive is pending or failed,
including the short undo window after approval. Once a download is in progress
or completed, approval is immutable and an approval-changing API request returns
HTTP 409. Illustration labels remain independently editable. Archived files are
served only when the item is approved and its download status is completed;
path traversal and unknown files are rejected.

On startup, work owned by the previous process is treated as interrupted before
the scheduler starts:

- queued or running refreshes become failed with an interruption message; start
  a new refresh from the UI or `POST /api/refresh`;
- in-progress downloads become failed without changing approval; retry them from
  the item UI or the retry-download endpoint;
- pending decisions and already completed downloads retain their durable state.

Refresh and download errors are stored in SQLite and remain visible through the
status and item APIs after a restart. Normal shutdown stops the scheduler and
disconnects the in-process event stream cleanly.

## Model identity

Built-in analysis profiles pin a literal Hugging Face commit revision and model
file SHA-256, and name the preprocessing and scoring contracts. Each analysis
copies `model_name`, `model_version`, `model_revision`, `model_sha256`,
`preprocessing_version`, and `scoring_version` into its durable result. Compare
results only when this identity and the relevant thresholds match. A result
identified only by a mutable `main` revision is not reproducible or comparable
with newly generated analysis. The built-in identities are defined in
`upvote_monitor/services/tagging/profiles.py` and summarized in
`docs/image-tagger-models.md`.

## Verification

Install the locked Python environment, then run the complete backend verification
from the repository root. The test command writes `coverage.xml`:

```console
uv sync
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest --cov=upvote_monitor --cov-report=xml
```

The application-level lifecycle suite can be run independently with:

```console
uv run pytest tests/test_app_lifecycle.py tests/test_api_integration.py tests/test_events.py
```

Verify the frontend separately:

```console
npm ci --prefix frontend
npm --prefix frontend run check
npm --prefix frontend run test
npm --prefix frontend run build
```
