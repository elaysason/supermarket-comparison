# Sal Kal / Supermarket Comparison

Sal Kal helps shoppers compare an online grocery cart against supported Israeli
supermarket chains and see where the same barcode-matched cart is cheaper,
including delivery or pickup fees when data is available.

The project combines three pieces:

- A FastAPI comparison API in `app/api/`.
- Chain scrapers in `app/scrapers/` that load public price XML feeds into
  Supabase/Postgres.
- A Chrome extension in `extension/` that reads the active cart and calls the
  API.

Supported chains currently include Shufersal, Rami Levi, Yohananof, Hazi Hinam,
and Carrefour.

## What It Does

The scrapers download each chain's store and price files, normalize products and
prices, and upsert them into Postgres. The browser extension extracts cart
barcodes and quantities from supported supermarket sites. The API compares the
cart against configured online stores for competitor chains and returns the
cheapest available option.

Comparison is barcode-based. Sal Kal does not guess substitutions. Items that do
not exist in the shared matched set are returned as unmatched.

Shipping and pickup costs are included when the chain has configured shipping
rules. If the cart does not meet a chain's minimum order, that fulfillment option
is returned as unavailable instead of being silently ignored.

## Repository Layout

- `app/api/` - FastAPI app, request/response models, comparison logic.
- `app/db/` - Postgres repository and seed helpers.
- `app/scrapers/` - shared scraper code and chain-specific implementations.
- `extension/` - Chrome extension source.
- `supabase/migrations/` - database schema migrations.
- `.github/workflows/scrape-prices.yml` - scheduled scraper workflow.
- `.github/workflows/deploy-api.yml` - Cloud Run API deployment workflow.
- `Dockerfile` - API container image for Cloud Run.

## Local Development

Requirements:

- Python `>=3.10`.
- `uv` for dependency management.
- A Supabase/Postgres database matching `supabase/migrations/`.
- Chrome or Chromium for extension testing.

Install dependencies:

```bash
uv sync
```

Run the API:

```bash
uv run uvicorn app.api.main:app --reload
```

Check health:

```bash
curl http://127.0.0.1:8000/health
```

Lint and format:

```bash
uv run ruff check .
uv run black .
```

## Environment

Copy `.env.example` to `.env` for local development.

Important API variables:

- `DATABASE_URL` - Postgres connection string. Production should use a read-only
  API role.
- `ALLOWED_EXTENSION_ORIGINS` - comma-separated Chrome extension origins allowed
  to call `/api/compare`.
- `MAX_COMPARE_BARCODES`, `MAX_BARCODE_LENGTH`, `MAX_ITEM_QUANTITY` - request
  size limits for API protection.
- `DATABASE_POOL_MIN_SIZE`, `DATABASE_POOL_MAX_SIZE` - Postgres pool size per
  API instance. Production currently caps this at `1..3` connections per Cloud
  Run instance.
- `DATABASE_STATEMENT_TIMEOUT_MS` - Postgres statement timeout for API requests.
  Do not set this for scraper jobs that perform bulk writes.
- `ALLOW_LOCAL_ORIGINS` - optional local development CORS/origin override. Do
  not enable it in production.

Scraper jobs should use a separate write-capable database role.

## Scraping Data

Run a delta scrape where supported:

```bash
uv run python -m app.main
```

Force full price files for every chain:

```bash
uv run python -m app.main --force-full
```

The scraper downloads XML files locally and writes parsed products/prices to the
database. XML downloads and `chains_downloads/` are local artifacts and should
not be committed.

Production scraping runs from a GitHub self-hosted Windows runner on a local
Israeli network because some supermarket price sites block cloud/datacenter
traffic. The workflow supports scheduled delta runs, scheduled full runs, manual
runs, and scraper log artifacts.

## Browser Extension

Load the extension locally:

1. Open `chrome://extensions`.
2. Enable Developer Mode.
3. Click Load unpacked.
4. Select the `extension/` directory.

After changing `manifest.json` or `background.js`, reload the extension card and
refresh the supermarket cart page.

The API URL is currently hardcoded in `extension/background.js`, and the same
Cloud Run URL must be present in `extension/manifest.json` under
`host_permissions`.

## Production

The API runs on Google Cloud Run as `supermarket-comparison-api` in
`europe-west1`. Pushes to `main` automatically deploy the API when API,
database-access, dependency, Docker, `.gcloudignore`, or deployment workflow
files change. The workflow can also be run manually from GitHub Actions.

Production guardrails currently in place:

- Cloud Run max instances are capped at `3`.
- Cloud Run concurrency is capped at `3` to match the API DB pool max.
- API DB pool max is capped at `3` connections per instance.
- API request size limits are enforced before DB queries.
- Postgres statement timeout is configured for API requests.
- `DATABASE_URL` is loaded from GCP Secret Manager secret `SUPABASE_DB_URL`.
- Origin filtering only allows configured Chrome extension origins.

Operational checks:

```bash
curl https://YOUR_CLOUD_RUN_URL/health
uv run ruff check .
```

Origin filtering is useful for the Chrome extension, but it is not full public
API authentication. For a wider public launch, add stronger abuse protection or
rate limiting if traffic starts to become expensive.

## Database

Schema changes belong in `supabase/migrations/`. The comparison API expects
products, prices, stores, shipping costs, and configured compare stores to be
present.

The API should only need read permissions. Scraping and seed commands need write
permissions.
