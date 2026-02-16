# Deployment Guide

This guide walks through deploying X Unfurls to Google Cloud Platform using a CI/CD-first approach where **all infrastructure is managed via GitHub Actions** - no local Terraform execution required.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        GitHub Actions                            │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐  │
│  │ Build/Test  │───▶│ Build Images│───▶│ Terraform Apply     │  │
│  └─────────────┘    └─────────────┘    │ (Infrastructure +   │  │
│                                         │  Deploy Images)     │  │
│                                         └─────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                                │
                    Workload Identity Federation
                          (OIDC - keyless)
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Google Cloud Platform                       │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │ GCS Bucket   │  │ Artifact     │  │ Cloud Run             │  │
│  │ (TF State)   │  │ Registry     │  │ ├─ Webhook (public)   │  │
│  └──────────────┘  └──────────────┘  │ └─ Worker (internal)  │  │
│                                       └───────────────────────┘  │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │ Secret       │  │ Pub/Sub      │  │ Workload Identity     │  │
│  │ Manager      │  │ (Job Queue)  │  │ Federation            │  │
│  └──────────────┘  └──────────────┘  └───────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Prerequisites

- GCP project with billing enabled
- `gcloud` CLI installed and authenticated (for bootstrap only)
- `gh` CLI installed (GitHub CLI)
- GitHub repository created
- Slack workspace with admin access
- xAI API key

**Not required locally:** Terraform (runs only in CI)

## Deployment Phases

| Phase | What | Where | When |
|-------|------|-------|------|
| 1 | Slack App Setup | Slack Admin Console | Once |
| 2 | Bootstrap GCP | Local terminal (gcloud) | Once |
| 3 | Bootstrap CI | GitHub Actions | Once |
| 4 | Configure Slack URLs | Slack Admin Console | Once |
| 5 | Populate Secrets | Local terminal (gcloud) | Once |
| 6 | Test & Verify | Slack | Once |
| Ongoing | Deploy Updates | GitHub Actions (auto) | Every push |

---

## Phase 1: Slack App Setup

### 1.1 Create Slack App

1. Go to https://api.slack.com/apps
2. Click "Create New App" → "From scratch"
3. Name: "X Unfurls" (or your choice)
4. Select your workspace

### 1.2 Configure OAuth Scopes

Navigate to **OAuth & Permissions** and add these Bot Token Scopes:
- `links:read` - Receive link shared events
- `links:write` - Unfurl links
- `chat:write` - Post messages

### 1.3 Enable Event Subscriptions

1. Navigate to **Event Subscriptions**
2. Enable Events: **On**
3. Request URL: Leave blank for now (set in Phase 4)
4. Subscribe to Bot Events:
   - `link_shared`

### 1.4 Configure App Unfurl Domains

1. Still in **Event Subscriptions**, scroll to **App Unfurl Domains**
2. Add domains:
   - `x.com`
   - `twitter.com`

### 1.5 Enable Interactivity

1. Navigate to **Interactivity & Shortcuts**
2. Enable Interactivity: **On**
3. Request URL: Leave blank for now (set in Phase 4)

### 1.6 Install App to Workspace

1. Navigate to **Install App**
2. Click "Install to Workspace"
3. Authorize the app
4. **Save these values** (needed in Phase 5):
   - **Bot User OAuth Token** (starts with `xoxb-`) from Install App page
   - **Signing Secret** from Basic Information page

---

## Phase 2: Bootstrap GCP Resources

This phase creates the minimal GCP resources needed before CI can take over. Run these commands locally **once**.

### 2.1 Set Environment Variables

```bash
# Your GCP project ID
export PROJECT_ID="your-gcp-project-id"

# Your GitHub username or organization
export GITHUB_OWNER="your-github-username"

# Set gcloud project
gcloud config set project $PROJECT_ID
```

### 2.2 Get Required IDs

```bash
# Get GCP project number
gcloud projects describe $PROJECT_ID --format='value(projectNumber)'
# Save this as PROJECT_NUMBER

# Get GitHub numeric owner ID (prevents repo squatting attacks)
gh api users/$GITHUB_OWNER --jq .id
# Save this as GITHUB_OWNER_ID
```

### 2.3 Create Terraform State Bucket

```bash
# Create GCS bucket for Terraform remote state
gsutil mb -l us-central1 gs://${PROJECT_ID}-terraform-state

# Enable versioning for state recovery
gsutil versioning set on gs://${PROJECT_ID}-terraform-state
```

### 2.4 Create Bootstrap Service Account

For the first CI run, we need a service account key (temporary - removed after Workload Identity Federation is created).

```bash
# Create bootstrap service account
gcloud iam service-accounts create x-unfurls-bootstrap \
  --display-name="X Unfurls Bootstrap (TEMPORARY)"

# Grant required permissions for initial terraform apply
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:x-unfurls-bootstrap@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/editor"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:x-unfurls-bootstrap@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/iam.securityAdmin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:x-unfurls-bootstrap@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/resourcemanager.projectIamAdmin"

# Create and download key (TEMPORARY - will be deleted after bootstrap)
gcloud iam service-accounts keys create bootstrap-key.json \
  --iam-account=x-unfurls-bootstrap@${PROJECT_ID}.iam.gserviceaccount.com

# Display the key (you'll paste this into GitHub)
cat bootstrap-key.json
```

⚠️ **Security Note:** This key is temporary. We'll delete it after the first successful deployment creates Workload Identity Federation.

---

## Phase 3: Bootstrap CI Pipeline

### 3.1 Configure GitHub Repository Variables

Go to your GitHub repository → **Settings** → **Secrets and variables** → **Actions**

Add these **Variables** (Variables tab):

| Variable | Value | Example |
|----------|-------|---------|
| `GCP_PROJECT_ID` | Your GCP project ID | `my-project-123` |
| `GCP_PROJECT_NUMBER` | From step 2.2 | `123456789012` |
| `GH_REPO_OWNER_ID` | From step 2.2 | `12345678` |

### 3.2 Configure GitHub Repository Secrets

Add these **Secrets** (Secrets tab):

| Secret | Value |
|--------|-------|
| `GCP_BOOTSTRAP_CREDENTIALS` | Contents of `bootstrap-key.json` from step 2.4 |

### 3.3 Trigger Bootstrap Deployment

Push to main to trigger the first deployment:

```bash
git add .
git commit -m "Bootstrap deployment"
git push origin main
```

The workflow will:
1. Authenticate using the bootstrap service account key
2. Run `terraform apply` to create all infrastructure including Workload Identity Federation
3. Build and deploy the Docker images

### 3.4 Capture Terraform Outputs

After the first successful run, get the Workload Identity outputs from the GitHub Actions logs or run:

```bash
# Get Workload Identity Provider path
gcloud iam workload-identity-pools providers describe github-provider \
  --workload-identity-pool=github-actions-pool \
  --location=global \
  --format='value(name)'

# Get CI/CD service account email
echo "x-unfurls-cicd@${PROJECT_ID}.iam.gserviceaccount.com"
```

### 3.5 Switch to Workload Identity Federation

Now that WIF exists, update GitHub to use keyless authentication:

1. Go to **Settings** → **Secrets and variables** → **Actions** → **Variables**

2. Add these variables:

| Variable | Value |
|----------|-------|
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Output from step 3.4 (full path starting with `projects/`) |
| `GCP_CICD_SERVICE_ACCOUNT` | `x-unfurls-cicd@PROJECT_ID.iam.gserviceaccount.com` |

3. **Delete the bootstrap secret:**
   - Go to **Secrets** tab
   - Delete `GCP_BOOTSTRAP_CREDENTIALS`

### 3.6 Clean Up Bootstrap Service Account

```bash
# Delete the local key file
rm bootstrap-key.json

# Delete all keys for the bootstrap service account
gcloud iam service-accounts keys list \
  --iam-account=x-unfurls-bootstrap@${PROJECT_ID}.iam.gserviceaccount.com \
  --format='value(name)' | xargs -I {} gcloud iam service-accounts keys delete {} \
  --iam-account=x-unfurls-bootstrap@${PROJECT_ID}.iam.gserviceaccount.com --quiet

# Optionally delete the bootstrap service account entirely
gcloud iam service-accounts delete x-unfurls-bootstrap@${PROJECT_ID}.iam.gserviceaccount.com --quiet
```

### 3.7 Verify Keyless Authentication

Push a small change to verify the pipeline works with Workload Identity Federation:

```bash
git commit --allow-empty -m "Verify WIF authentication"
git push origin main
```

Check GitHub Actions - it should authenticate without the bootstrap credentials.

---

## Phase 4: Configure Slack URLs

After successful deployment, configure Slack to send events to your webhook.

### 4.1 Get Webhook URL

From GitHub Actions output or:

```bash
gcloud run services describe x-unfurls-webhook \
  --region=us-central1 \
  --format='value(status.url)'
```

### 4.2 Update Slack Event Subscriptions

1. Go to your Slack App → **Event Subscriptions**
2. Set Request URL: `https://YOUR_WEBHOOK_URL/slack/events`
3. Wait for verification checkmark ✅

### 4.3 Update Slack Interactivity

1. Go to **Interactivity & Shortcuts**
2. Set Request URL: `https://YOUR_WEBHOOK_URL/slack/interactive`

### 4.4 Reinstall App

**Required** after changing unfurl domains:

1. Go to **Install App**
2. Click "Reinstall to Workspace"
3. Authorize

---

## Phase 5: Populate Secrets

Add the actual secret values to GCP Secret Manager:

```bash
# Slack Bot Token (from Phase 1.6)
echo -n "xoxb-your-bot-token-here" | \
  gcloud secrets versions add x-unfurls-slack-bot-token --data-file=-

# Slack Signing Secret (from Phase 1.6)
echo -n "your-signing-secret-here" | \
  gcloud secrets versions add x-unfurls-slack-signing-secret --data-file=-

# xAI API Key
echo -n "your-xai-api-key-here" | \
  gcloud secrets versions add x-unfurls-xai-api-key --data-file=-
```

**Note:** Use `echo -n` to avoid trailing newlines in secrets.

---

## Phase 6: Test & Verify

### 6.1 Test the Integration

1. Open any Slack channel in your workspace
2. Post an X/Twitter URL:
   ```
   https://x.com/OpenAI/status/1234567890
   ```
3. Within a few seconds, you should see a rich unfurl with:
   - Author info and avatar
   - Full post text
   - Engagement metrics
   - Top replies (if any)
   - Grok AI summary

### 6.2 Check Logs if Issues

```bash
# Webhook service logs
gcloud run services logs read x-unfurls-webhook --region=us-central1 --limit=20

# Worker service logs
gcloud run services logs read x-unfurls-worker --region=us-central1 --limit=20
```

### 6.3 Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| "Invalid signature" | Wrong signing secret | Re-add secret in Phase 5 |
| No unfurl appears | App not installed properly | Reinstall app (Phase 4.4) |
| Unfurl domains not working | Domains not registered | Check Event Subscriptions → App Unfurl Domains |
| Pub/Sub permission denied | IAM misconfigured | Re-run `terraform apply` via CI |

---

## Ongoing: Deploy Updates

After initial setup, deployments are fully automated:

```bash
# Make changes
git add .
git commit -m "Your changes"
git push origin main
```

GitHub Actions will:
1. ✅ Run tests and linting
2. ✅ Build Docker images
3. ✅ Push to Artifact Registry
4. ✅ Run `terraform apply` (updates infrastructure + deploys images)
5. ✅ Verify deployment

### Infrastructure Changes

All infrastructure changes go through the same pipeline:

1. Edit files in `infra_gcp/terraform/`
2. Commit and push to `main`
3. Terraform applies changes automatically

**Benefits:**
- No local Terraform state
- No credential management
- Infrastructure drift is automatically corrected
- Full audit trail in git history

---

## Monitoring

### View Logs

```bash
# Webhook logs (recent)
gcloud run services logs read x-unfurls-webhook --region=us-central1 --limit=50

# Worker logs with filter
gcloud run services logs read x-unfurls-worker --region=us-central1 \
  --filter='jsonPayload.event="xai_fetch_success"'

# Tail logs in real-time
gcloud beta run services logs tail x-unfurls-webhook --region=us-central1
```

### Check Pub/Sub Queue

```bash
# View pending messages (if any stuck)
gcloud pubsub subscriptions describe x-unfurls-jobs-push

# Check dead letter queue for failed jobs
gcloud pubsub subscriptions pull x-unfurls-jobs-dlq-pull --limit=10 --auto-ack
```

### Service Health

```bash
# Check service status
gcloud run services describe x-unfurls-webhook --region=us-central1 \
  --format='table(status.conditions.type,status.conditions.status)'

gcloud run services describe x-unfurls-worker --region=us-central1 \
  --format='table(status.conditions.type,status.conditions.status)'
```

---

## Cost Management

Expected monthly costs (free tier):

| Resource | Cost | Notes |
|----------|------|-------|
| Cloud Run | $0 | Under 2M requests/month |
| Pub/Sub | $0 | Under 10 GiB/month |
| Secret Manager | $0 | 3 secrets, minimal access |
| Artifact Registry | $0-5 | Watch storage usage |
| GCS (TF state) | $0 | Minimal storage |

**Total: $0-5/month** for a 7-person workspace

### Reduce Artifact Registry Costs

The Terraform config includes a cleanup policy keeping only the 3 most recent image versions. Monitor with:

```bash
gcloud artifacts docker images list \
  us-central1-docker.pkg.dev/${PROJECT_ID}/x-unfurls \
  --include-tags
```

---

## Teardown

To destroy all infrastructure:

1. Push a change that runs `terraform destroy`:
   ```bash
   # Or run manually with appropriate credentials
   cd infra_gcp/terraform
   terraform destroy
   ```

2. Delete the state bucket:
   ```bash
   gsutil rm -r gs://${PROJECT_ID}-terraform-state
   ```

3. Remove the Slack app:
   - Go to https://api.slack.com/apps
   - Select your app → Settings → Delete App

---

## Security Notes

### Workload Identity Federation

After bootstrap, the CI/CD pipeline uses **keyless authentication**:
- No service account keys stored in GitHub
- OIDC tokens exchanged for short-lived GCP credentials
- Restricted to `main` branch of your specific repository
- Uses numeric GitHub owner ID to prevent username squatting attacks

### Secret Management

- All secrets stored in GCP Secret Manager
- No secrets in code or environment variables
- Cloud Run services access secrets at runtime via IAM

### Network Security

- Webhook service: Public (required for Slack)
- Worker service: Internal only (Pub/Sub push via OIDC)
- No direct internet access from worker
