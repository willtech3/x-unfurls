# =============================================================================
# Runtime Service Accounts
# =============================================================================

resource "google_service_account" "webhook_runtime" {
  account_id   = "x-unfurls-webhook"
  display_name = "X Unfurls - Webhook (Cloud Run)"
  description  = "Runtime service account for webhook Cloud Run service"

  depends_on = [google_project_service.iam]
}

resource "google_service_account" "worker_runtime" {
  account_id   = "x-unfurls-worker"
  display_name = "X Unfurls - Worker (Cloud Run)"
  description  = "Runtime service account for worker Cloud Run service"

  depends_on = [google_project_service.iam]
}

resource "google_service_account" "pubsub_push_invoker" {
  account_id   = "x-unfurls-pubsub-invoker"
  display_name = "X Unfurls - Pub/Sub Push Invoker"
  description  = "Service account for Pub/Sub push subscription OIDC authentication"

  depends_on = [google_project_service.iam]
}

# =============================================================================
# Secret Manager IAM
# =============================================================================

locals {
  webhook_secret_ids = [
    google_secret_manager_secret.slack_bot_token.secret_id,
    google_secret_manager_secret.slack_signing_secret.secret_id,
  ]

  worker_secret_ids = [
    google_secret_manager_secret.slack_bot_token.secret_id,
    google_secret_manager_secret.xai_api_key.secret_id,
  ]
}

resource "google_secret_manager_secret_iam_member" "webhook_secret_access" {
  for_each  = toset(local.webhook_secret_ids)
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.webhook_runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "worker_secret_access" {
  for_each  = toset(local.worker_secret_ids)
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.worker_runtime.email}"
}

# =============================================================================
# Pub/Sub IAM
# =============================================================================

resource "google_pubsub_topic_iam_member" "webhook_publisher" {
  topic  = google_pubsub_topic.jobs.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.webhook_runtime.email}"
}

resource "google_project_service_identity" "pubsub_agent" {
  provider = google-beta
  project  = var.project_id
  service  = "pubsub.googleapis.com"

  depends_on = [google_project_service.pubsub]
}

resource "google_service_account_iam_member" "pubsub_token_creator" {
  service_account_id = google_service_account.pubsub_push_invoker.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_project_service_identity.pubsub_agent.email}"
}

resource "google_pubsub_topic_iam_member" "dlq_publisher" {
  topic  = google_pubsub_topic.jobs_dlq.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_project_service_identity.pubsub_agent.email}"
}

resource "google_pubsub_subscription_iam_member" "subscription_subscriber_for_dlq" {
  subscription = google_pubsub_subscription.jobs_push.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${google_project_service_identity.pubsub_agent.email}"
}
