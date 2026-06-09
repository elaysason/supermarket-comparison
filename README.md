# supermarket-comparison

## Deploy API to Google Cloud Run

The API is deployable as a container. Cloud Run is a good low-cost/free-tier
fit because it can scale to zero and provides a public HTTPS URL.

Recommended settings:

```bash
gcloud run deploy supermarket-comparison-api \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --min-instances 0 \
  --set-env-vars DATABASE_URL="postgresql://postgres:YOUR_PASSWORD@db.YOUR_PROJECT_REF.supabase.co:5432/postgres?sslmode=require"
```

After deployment, verify:

```bash
curl https://YOUR_CLOUD_RUN_URL/health
```

Then update the browser extension API URL and `host_permissions` to the Cloud
Run URL.
