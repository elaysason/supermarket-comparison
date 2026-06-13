# Sal Kal / Supermarket Comparison

Sal Kal helps shoppers compare an online grocery cart against other supported
Israeli supermarket chains and see where the same cart is cheaper, including
delivery or pickup fees when available.

The project has three main parts:

- A FastAPI comparison API in `app/api/`.
- Scrapers in `app/scrapers/` that load public chain price XML data into Postgres.
- A Chrome extension in `extension/` that reads the active supermarket cart and
  calls the API.

Supported chains currently include Shufersal, Rami Levi, Yohananof, Hazi Hinam,
and Carrefour.

## How It Works

1. Scrapers download each chain's latest store and price files.
2. Parsed products and prices are upserted into Supabase/Postgres.
3. The browser extension extracts cart barcodes and quantities from supported
   supermarket sites.
4. The API compares matching barcodes across configured online stores and returns
   the cheapest available competitor total.

The comparison is barcode-based. Items that do not exist in the shared matched
set are reported as unmatched instead of guessed.

## Repository Layout

- `app/api/` - FastAPI app, request/response models, comparison logic.
- `app/db/` - Postgres repository and seed helpers.
- `app/scrapers/` - chain-specific scraper implementations.
- `extension/` - Chrome extension source.
- `supabase/migrations/` - database schema migrations.
- `.github/workflows/scrape-prices.yml` - scheduled scraper workflow.
- `.github/workflows/deploy-api.yml` - Cloud Run API deployment workflow.
- `Dockerfile` - API container image for Cloud Run.

## Requirements

- Python `>=3.10`.
- `uv` for dependency management.
- A Supabase/Postgres database matching the migrations in `supabase/migrations/`.
- Chrome or Chromium for the extension.

## Environment

Copy `.env.example` to `.env` for local development and set the database values.

Important production variables:

- `DATABASE_URL` - Postgres connection string. Use a read-only DB role for the
  API and a separate write role for the scraper job.
- `ALLOWED_EXTENSION_ORIGINS` - comma-separated allowed Chrome extension origins.
  Current unpacked dev origin: `chrome-extension://lpanbbdfjojpggjjigbeohneelcmheln`.
  Replace it when Chrome gives you a different unpacked ID or a Chrome Web Store
  extension ID.
- `MAX_COMPARE_BARCODES` - maximum barcodes accepted by `/api/compare`.
- `MAX_BARCODE_LENGTH` - maximum single barcode length.
- `MAX_ITEM_QUANTITY` - maximum quantity accepted for a single cart item.
- `DATABASE_STATEMENT_TIMEOUT_MS` - optional Postgres statement timeout. Set it
  on the API service, not on scraper jobs that perform bulk writes.
- `ALLOW_LOCAL_ORIGINS` - optionally allow localhost origins for local API work.
  Do not enable it in production.

## Local Development

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

Run linting:

```bash
uv run ruff check .
```

Format Python:

```bash
uv run black .
```

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

If running from a scheduler, use the scraper/write database role rather than the
read-only API role.

## Scraper Automation

Some Israeli supermarket price sites block cloud/datacenter traffic. For that
reason, production scraping is run from a local Israeli network using a GitHub
self-hosted runner.

Runner requirements:

- Windows x64 self-hosted runner installed on a machine with Israeli network
  access.
- Runner label: `salkal-scraper`.
- Repository secret: `DATABASE_URL` with scraper/write database permissions.
- Machine stays awake during scheduled runs.

Runner setup path in GitHub:

```text
Settings > Actions > Runners > New self-hosted runner
```

The workflow is defined in `.github/workflows/scrape-prices.yml`.

It supports:

- Scheduled delta scraping at `01:00 UTC` and `13:00 UTC`.
- Scheduled full scraping every other day at `02:00 UTC`.
- Manual runs from the GitHub Actions tab.
- A `force_full` option for manual full scrapes.
- Scraper logs uploaded as workflow artifacts.

The workflow only runs on `main` and installs dependencies with `uv sync
--frozen` so scheduled runs use the committed lockfile.

## Browser Extension

Load the extension locally:

1. Open `chrome://extensions`.
2. Enable Developer Mode.
3. Click Load unpacked.
4. Select the `extension/` directory.

After changing `manifest.json` or `background.js`, click Reload on the extension
card and refresh the supermarket cart page.

The extension API URL is currently hardcoded in `extension/background.js`, and
the same Cloud Run URL must appear in `extension/manifest.json` under
`host_permissions`.

For an unpacked extension, Chrome shows the extension ID on `chrome://extensions`.
Allow that origin in the API as `chrome-extension://THE_ID`.

## Deploy API to Cloud Run

The API is deployable as a container. Cloud Run is a good fit because it provides
a public HTTPS URL and can scale to zero.

Pushes to `main` automatically deploy the API when API, database access,
dependency, Docker, or deployment workflow files change. The workflow is defined
in `.github/workflows/deploy-api.yml` and can also be run manually from the
GitHub Actions tab.

Required GitHub repository secrets:

- `GCP_WORKLOAD_IDENTITY_PROVIDER` - Workload Identity Provider resource name.
- `GCP_SERVICE_ACCOUNT` - deploy service account email.

Required GitHub repository variables:

- `GCP_PROJECT_ID` - `salkal-498916`.
- `GCP_REGION` - `europe-west1`.
- `CLOUD_RUN_SERVICE` - `supermarket-comparison-api`.
- `ALLOWED_EXTENSION_ORIGINS` - `chrome-extension://lpanbbdfjojpggjjigbeohneelcmheln`.
- `DATABASE_URL_SECRET_NAME` - Secret Manager secret name containing
  `DATABASE_URL`: `SUPABASE_DB_URL`.

The deploy service account needs permission to deploy Cloud Run from source,
write build artifacts, and read the configured Secret Manager secret.

One-time GitHub/GCP setup, from a machine with `gcloud` and `gh` installed:

```bash
PROJECT_ID="salkal-498916"
PROJECT_NUMBER="649951889970"
REGION="europe-west1"
REPO="elaysason/supermarket-comparison"
POOL_ID="github-actions"
PROVIDER_ID="github"
SERVICE_ACCOUNT="github-cloud-run-deploy"
SECRET_NAME="SUPABASE_DB_URL"

gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com iamcredentials.googleapis.com \
  secretmanager.googleapis.com \
  --project "$PROJECT_ID" --quiet

gcloud iam workload-identity-pools create "$POOL_ID" \
  --project "$PROJECT_ID" \
  --location global \
  --display-name "GitHub Actions" \
  --quiet

gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
  --project "$PROJECT_ID" \
  --location global \
  --workload-identity-pool "$POOL_ID" \
  --display-name "GitHub" \
  --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition "attribute.repository == '$REPO' && assertion.ref == 'refs/heads/main'" \
  --issuer-uri "https://token.actions.githubusercontent.com" \
  --quiet

gcloud iam service-accounts create "$SERVICE_ACCOUNT" \
  --project "$PROJECT_ID" \
  --display-name "GitHub Cloud Run deploy" \
  --quiet

DEPLOYER="$SERVICE_ACCOUNT@$PROJECT_ID.iam.gserviceaccount.com"
PROVIDER="projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL_ID/providers/$PROVIDER_ID"
RUNTIME_SERVICE_ACCOUNT="$PROJECT_NUMBER-compute@developer.gserviceaccount.com"

gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER" \
  --project "$PROJECT_ID" \
  --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL_ID/attribute.repository/$REPO" \
  --quiet

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member "serviceAccount:$DEPLOYER" \
  --role roles/run.admin \
  --quiet

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member "serviceAccount:$DEPLOYER" \
  --role roles/run.sourceDeveloper \
  --quiet

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member "serviceAccount:$DEPLOYER" \
  --role roles/logging.viewer \
  --quiet

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member "serviceAccount:$DEPLOYER" \
  --role roles/serviceusage.serviceUsageConsumer \
  --quiet

gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SERVICE_ACCOUNT" \
  --project "$PROJECT_ID" \
  --member "serviceAccount:$DEPLOYER" \
  --role roles/iam.serviceAccountUser \
  --quiet

gcloud secrets add-iam-policy-binding "$SECRET_NAME" \
  --project "$PROJECT_ID" \
  --member "serviceAccount:$DEPLOYER" \
  --role roles/secretmanager.secretAccessor \
  --quiet

gcloud secrets add-iam-policy-binding "$SECRET_NAME" \
  --project "$PROJECT_ID" \
  --member "serviceAccount:$RUNTIME_SERVICE_ACCOUNT" \
  --role roles/secretmanager.secretAccessor \
  --quiet

gh variable set GCP_PROJECT_ID --repo "$REPO" --body "$PROJECT_ID"
gh variable set GCP_REGION --repo "$REPO" --body "$REGION"
gh variable set CLOUD_RUN_SERVICE --repo "$REPO" --body "supermarket-comparison-api"
gh variable set ALLOWED_EXTENSION_ORIGINS --repo "$REPO" --body "chrome-extension://lpanbbdfjojpggjjigbeohneelcmheln"
gh variable set DATABASE_URL_SECRET_NAME --repo "$REPO" --body "$SECRET_NAME"
gh secret set GCP_WORKLOAD_IDENTITY_PROVIDER --repo "$REPO" --body "$PROVIDER"
gh secret set GCP_SERVICE_ACCOUNT --repo "$REPO" --body "$DEPLOYER"
```

Recommended deploy command:

```bash
gcloud run deploy supermarket-comparison-api \
  --source . \
  --region europe-west1 \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 3 \
  --concurrency 5 \
  --set-env-vars ALLOWED_EXTENSION_ORIGINS="chrome-extension://lpanbbdfjojpggjjigbeohneelcmheln" \
  --set-env-vars MAX_COMPARE_BARCODES=100,MAX_BARCODE_LENGTH=64,MAX_ITEM_QUANTITY=99,DATABASE_STATEMENT_TIMEOUT_MS=10000 \
  --update-secrets DATABASE_URL=SUPABASE_DB_URL:latest
```

After deployment, verify the service starts:

```bash
curl https://YOUR_CLOUD_RUN_URL/health
```

Then verify origin filtering after deployment. Your extension origin should pass,
and a random extension origin should return `403`.

## Deployment Notes

- Store `DATABASE_URL` in GCP Secret Manager, not plain environment variables.
- Keep `--max-instances` bounded so Cloud Run cannot exhaust Supabase
  connections.
- Keep `--concurrency` close to the API DB pool size. The current pool is 5
  connections per instance.
- Use the Supabase pooler connection string if the runtime cannot reach the
  direct database endpoint.
- `/health` only proves the API process is alive; test `/api/compare` to verify
  the database path.
- `ALLOWED_EXTENSION_ORIGINS` is browser-origin filtering, not real auth. Keep
  Cloud Run instance limits in place and put the service behind HTTPS Load
  Balancing with Cloud Armor rate limiting before relying on it as a public
  production endpoint.
- Redeploy the API after changing origin, limit, or secret settings.

## Database

Apply schema changes through `supabase/migrations/`. The comparison API expects
products, prices, stores, shipping costs, and configured compare stores to be
present.

The API should only need read permissions. Scraping and seed commands need write
permissions.
