# supermarket-comparison

Compare Israeli supermarket cart prices with a FastAPI backend, Supabase data,
chain scrapers, and a Chrome extension.

## Project Layout

- `app/api/` - FastAPI API used by the browser extension.
- `app/scrapers/` - chain-specific supermarket scrapers.
- `app/db/` - Supabase/Postgres repository and seed utilities.
- `extension/` - Chrome extension files.
- `supabase/migrations/` - database schema migrations.

## Local Development

Install dependencies:

```bash
uv sync
```

Run the API locally:

```bash
uv run uvicorn app.api.main:app --reload
```

Run the scraper with the default update strategy:

```bash
uv run python -m app.main
```

Run a full scrape:

```bash
uv run python -m app.main --force-full
```

Verify Python code:

```bash
uv run black .
uv run ruff check .
```

## Environment

Production should use `DATABASE_URL`:

```text
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@db.YOUR_PROJECT_REF.supabase.co:5432/postgres?sslmode=require
```

The legacy local keys in `.env.example` are still supported for local use.
Use least-privilege database credentials in production. Prefer separate
credentials for the API and scraper when possible, because the scraper needs
write access while the API only needs read access for comparisons.

## API Deployment

The FastAPI API runs on Google Cloud Run from the repo `Dockerfile`.

Recommended Cloud Run settings:

- Service type: Cloud Run service
- Build type: Dockerfile
- Dockerfile path: `Dockerfile`
- Authentication: allow unauthenticated requests
- Container port: `8000`
- Minimum instances: `0`
- Env var: `DATABASE_URL`

Verify the deployed API:

```bash
curl https://YOUR_CLOUD_RUN_URL/health
```

Expected response:

```json
{"status":"ok"}
```

After API deployment, update `extension/background.js` and
`extension/manifest.json` with the Cloud Run URL.

## Scraper Automation

Some Israeli supermarket price sites block cloud/datacenter traffic. For that
reason, production scraping is run from a local Israeli network using a GitHub
self-hosted runner.

Runner requirements:

- Windows x64 self-hosted runner installed on a machine with Israeli network
  access.
- Runner label: `salkal-scraper`.
- Repository secret: `DATABASE_URL`.
- Machine stays awake during scheduled runs.

Runner setup path in GitHub:

```text
Settings > Actions > Runners > New self-hosted runner
```

The workflow is defined in `.github/workflows/scrape-prices.yml`.

It supports:

- Daily scheduled scraping at `01:00 UTC`.
- Manual runs from the GitHub Actions tab.
- A `force_full` option for manual full scrapes.
- Scraper logs uploaded as workflow artifacts.

The workflow only runs on `main` and installs dependencies with `uv sync
--frozen` so scheduled runs use the committed lockfile.

## Extension Testing

Load the extension unpacked from `extension/` in Chrome:

```text
chrome://extensions
```

After changing `manifest.json` or `background.js`, click Reload on the extension
card and refresh the supermarket cart page.
