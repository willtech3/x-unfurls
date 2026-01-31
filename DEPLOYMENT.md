# Deployment Guide

This guide walks through deploying X Unfurls to Google Cloud Platform.

## Prerequisites

- GCP project with billing enabled
- `gcloud` CLI installed and authenticated
- `terraform` >= 1.6.0 installed
- GitHub repository created
- Slack workspace with admin access
- xAI API key

## Step 1: Slack App Setup

### 1.1 Create Slack App

1. Go to https://api.slack.com/apps
2. Click "Create New App" → "From scratch"
3. Name: "X Unfurls" (or your choice)
4. Select your workspace

### 1.2 Configure OAuth Scopes

Navigate to **OAuth & Permissions** and add these Bot Token Scopes:
- `links:read` - Receive link info
- `links:write` - Perform unfurling
- `chat:write` - Post/update via Web API

### 1.3 Enable Event Subscriptions

1. Navigate to **Event Subscriptions**
2. Enable Events: **On**
3. Request URL: (We'll set this after deploying - leave blank for now)
4. Subscribe to Bot Events:
   - `link_shared`

### 1.4 Configure App Unfurl Domains

1. Still in **Event Subscriptions**, scroll to **App Unfurl Domains**
2. Add domains:
   - `x.com`
   - `twitter.com`

### 1.5 Enable Interactivity (Optional - for action buttons)

1. Navigate to **Interactivity & Shortcuts**
2. Enable Interactivity: **On**
3. Request URL: (Same as events URL, we'll set later)

### 1.6 Install App to Workspace

1. Navigate to **Install App**
2. Click "Install to Workspace"
3. Authorize the app
4. Copy the **Bot User OAuth Token** (starts with `xoxb-`)
5. Navigate to **Basic Information** and copy the **Signing Secret**

Save these values - you'll need them for secrets.

## Step 2: GCP Infrastructure Setup

### 2.1 Enable APIs and Set Up Project

```bash
# Set your project
export PROJECT_ID="your-gcp-project-id"
gcloud config set project $PROJECT_ID

# Enable billing if not already enabled
gcloud beta billing projects link $PROJECT_ID --billing-account=YOUR_BILLING_ACCOUNT_ID
```

### 2.2 Get GitHub Owner ID

```bash
# Get your GitHub numeric owner ID (prevents repo squatting attacks)
gh api users/YOUR_GITHUB_USERNAME --jq .id
```

### 2.3 Configure Terraform Variables

```bash
cd infra_gcp/terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`:
```hcl
project_id           = "your-gcp-project-id"
region               = "us-central1"
github_repo_owner    = "your-github-username"
github_repo_name     = "x-unfurls"
github_repo_owner_id = "123456789"  # From step 2.2
```

### 2.4 Deploy Infrastructure

```bash
cd infra_gcp/terraform

# Initialize Terraform
terraform init

# Review the plan
terraform plan

# Apply (creates all GCP resources)
terraform apply
```

Save the outputs - you'll need them for GitHub Actions and Slack configuration.

### 2.5 Populate Secrets

```bash
# Set secrets in GCP Secret Manager
echo "xoxb-your-bot-token" | gcloud secrets versions add x-unfurls-slack-bot-token --data-file=-
echo "your-signing-secret" | gcloud secrets versions add x-unfurls-slack-signing-secret --data-file=-
echo "your-xai-api-key" | gcloud secrets versions add x-unfurls-xai-api-key --data-file=-
```

## Step 3: GitHub Actions Setup

### 3.1 Configure Repository Variables

Go to your GitHub repository → Settings → Secrets and variables → Actions → Variables

Add these **Variables** (not secrets):
- `GCP_PROJECT_ID`: Your GCP project ID
- `GCP_PROJECT_NUMBER`: Your GCP project number (from `gcloud projects describe $PROJECT_ID`)
- `GCP_WORKLOAD_IDENTITY_PROVIDER`: From Terraform output `workload_identity_provider`
- `GCP_CICD_SERVICE_ACCOUNT`: From Terraform output `cicd_service_account_email`

### 3.2 Trigger First Deployment

```bash
# Commit and push to main
git add .
git commit -m "Initial deployment"
git push origin main
```

GitHub Actions will:
1. Run tests and linting
2. Build Docker images
3. Push to Artifact Registry
4. Deploy to Cloud Run

## Step 4: Update Slack App URLs

After the first deployment:

1. Get the webhook URL from GitHub Actions output or:
   ```bash
   gcloud run services describe x-unfurls-webhook --region=us-central1 --format='value(status.url)'
   ```

2. Go to your Slack App → **Event Subscriptions**:
   - Request URL: `https://your-webhook-url/slack/events`
   - Slack will verify the URL (should show ✅ Verified)

3. Go to **Interactivity & Shortcuts**:
   - Request URL: `https://your-webhook-url/slack/interactive`

4. **Reinstall the app** to your workspace (required after changing unfurl domains):
   - Settings → Install App → Reinstall to Workspace

## Step 5: Test the Integration

1. Open any Slack channel where the app is installed
2. Post an X/Twitter URL, e.g.:
   ```
   https://x.com/example/status/1234567890
   ```
3. You should see a rich unfurl appear within a few seconds!

## Step 6: Monitoring and Debugging

### View Logs

```bash
# Webhook logs
gcloud run services logs read x-unfurls-webhook --region=us-central1 --limit=50

# Worker logs
gcloud run services logs read x-unfurls-worker --region=us-central1 --limit=50

# Filter by event type
gcloud run services logs read x-unfurls-worker --region=us-central1 --filter='jsonPayload.event="job_received"'
```

### Check Pub/Sub

```bash
# View topic
gcloud pubsub topics describe x-unfurls-jobs

# View subscription
gcloud pubsub subscriptions describe x-unfurls-jobs-push

# Check dead letter queue
gcloud pubsub subscriptions pull x-unfurls-jobs-dlq-pull --limit=10
```

### Common Issues

**"Invalid signature" errors:**
- Verify `SLACK_SIGNING_SECRET` in Secret Manager matches your Slack app

**"No unfurl appears":**
- Check Cloud Logging for errors
- Verify the app is installed and has correct scopes
- Ensure unfurl domains (`x.com`, `twitter.com`) are registered
- Reinstall the app after changing domains

**"Pub/Sub permission denied":**
- Verify service account IAM bindings in Terraform
- Check that Pub/Sub push subscription has correct OIDC token config

## Step 7: Optional - Remove Slack's Native X Preview

If you see both your custom unfurl AND Slack's native X preview:

1. Go to your Slack workspace settings (admin required)
2. Navigate to **Settings & permissions** → **Permissions** → **Manage link previews**
3. Block previews from:
   - `x.com`
   - `twitter.com`

This keeps other link previews enabled while removing only X previews.

## Updating the Application

To deploy updates:

```bash
# Make your changes
git add .
git commit -m "Your changes"
git push origin main
```

GitHub Actions will automatically rebuild and deploy.

## Cost Management

Expected costs with free tier:
- **Cloud Run**: Free (well under 2M requests/month)
- **Pub/Sub**: Free (under 10 GiB/month)
- **Secret Manager**: Free (3 secrets, under 10K accesses)
- **Artifact Registry**: ~$0-5/month (watch storage)

To minimize costs:
- Set `min_instance_count = 0` in Cloud Run (auto-scale to zero)
- Monitor Artifact Registry storage and clean old images
- Review Cloud Logging retention settings

## Teardown

To destroy all infrastructure:

```bash
cd infra_gcp/terraform
terraform destroy
```

Note: This does NOT delete:
- Container images in Artifact Registry (delete manually if needed)
- Cloud Logging data
