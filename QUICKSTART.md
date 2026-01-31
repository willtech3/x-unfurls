# Quick Start Guide

Get X Unfurls running in under 30 minutes.

## Prerequisites Checklist

- [ ] GCP account with billing enabled
- [ ] `gcloud` CLI installed ([Install](https://cloud.google.com/sdk/docs/install))
- [ ] `terraform` installed ([Install](https://developer.hashicorp.com/terraform/install))
- [ ] GitHub account
- [ ] Slack workspace (admin access)
- [ ] xAI API key ([Get one](https://x.ai))

## Step 1: Clone and Configure (5 min)

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/x-unfurls.git
cd x-unfurls

# Install Python dependencies
uv sync

# Run tests to verify setup
uv run pytest
```

## Step 2: Create Slack App (5 min)

1. Go to https://api.slack.com/apps → **Create New App** → **From scratch**
2. Name it "X Unfurls", select your workspace
3. **OAuth & Permissions** → Add Bot Token Scopes:
   - `links:read`
   - `links:write`
   - `chat:write`
4. **Event Subscriptions** → Enable → Add Bot Events:
   - `link_shared`
5. **Event Subscriptions** → App Unfurl Domains → Add:
   - `x.com`
   - `twitter.com`
6. **Install App** → Install to workspace
7. Copy **Bot Token** (`xoxb-...`) and **Signing Secret**

## Step 3: Deploy to GCP (10 min)

```bash
# Set your GCP project
export PROJECT_ID="your-project-id"
gcloud config set project $PROJECT_ID

# Configure Terraform
cd infra_gcp/terraform
cp terraform.tfvars.example terraform.tfvars

# Edit terraform.tfvars with your values
# Get GitHub owner ID: gh api users/YOUR_USERNAME --jq .id
nano terraform.tfvars

# Deploy infrastructure
terraform init
terraform apply  # Type 'yes' when prompted

# Save the outputs (webhook URL, etc.)
```

## Step 4: Set Secrets (2 min)

```bash
# Add Slack bot token
echo "xoxb-your-token" | gcloud secrets versions add x-unfurls-slack-bot-token --data-file=-

# Add Slack signing secret
echo "your-signing-secret" | gcloud secrets versions add x-unfurls-slack-signing-secret --data-file=-

# Add xAI API key
echo "your-xai-key" | gcloud secrets versions add x-unfurls-xai-api-key --data-file=-
```

## Step 5: Configure GitHub Actions (5 min)

1. Go to your GitHub repo → **Settings** → **Secrets and variables** → **Actions** → **Variables**
2. Add these variables:
   ```
   GCP_PROJECT_ID = your-project-id
   GCP_PROJECT_NUMBER = (run: gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
   GCP_WORKLOAD_IDENTITY_PROVIDER = (from Terraform output)
   GCP_CICD_SERVICE_ACCOUNT = (from Terraform output)
   ```

## Step 6: Deploy Application (5 min)

```bash
# Commit and push to trigger deployment
git add .
git commit -m "Initial deployment"
git push origin main
```

Wait for GitHub Actions to complete (~3-5 minutes).

## Step 7: Connect Slack App (3 min)

1. Get webhook URL:
   ```bash
   gcloud run services describe x-unfurls-webhook --region=us-central1 --format='value(status.url)'
   ```

2. In your Slack app:
   - **Event Subscriptions** → Request URL: `https://YOUR_WEBHOOK_URL/slack/events`
   - Wait for ✅ Verified
   - **Interactivity** → Request URL: `https://YOUR_WEBHOOK_URL/slack/interactive`

3. **IMPORTANT**: Reinstall the app:
   - **Settings** → **Install App** → **Reinstall to Workspace**

## Step 8: Test It! (1 min)

1. Open any Slack channel
2. Post an X URL:
   ```
   https://x.com/elonmusk/status/1234567890
   ```
3. Watch the rich preview appear! 🎉

## Troubleshooting

**No unfurl appears?**
```bash
# Check webhook logs
gcloud run services logs read x-unfurls-webhook --region=us-central1 --limit=20

# Check worker logs
gcloud run services logs read x-unfurls-worker --region=us-central1 --limit=20
```

**"Invalid signature" error?**
- Verify signing secret in Secret Manager matches Slack app

**"Permission denied" error?**
- Ensure app is reinstalled after adding unfurl domains
- Check OAuth scopes are correct

## What's Next?

- [ ] Read [ARCHITECTURE.md](ARCHITECTURE.md) to understand the system
- [ ] Review [DEPLOYMENT.md](DEPLOYMENT.md) for advanced configuration
- [ ] Set up monitoring alerts in Cloud Logging
- [ ] (Optional) Block native X previews in Slack workspace settings

## Cost Estimate

**Expected monthly cost**: $0-5

Most services are within GCP free tier. Only cost is Artifact Registry storage (~$0.10/GB/month).

## Getting Help

- **Issues**: https://github.com/YOUR_USERNAME/x-unfurls/issues
- **Logs**: Cloud Logging in GCP Console
- **Slack API**: https://api.slack.com/apps
