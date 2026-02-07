# =============================================================================
# Pub/Sub Topics
# =============================================================================

resource "google_pubsub_topic" "jobs" {
  name = "x-unfurls-jobs"

  message_retention_duration = "604800s" # 7 days

  depends_on = [google_project_service.pubsub]
}

resource "google_pubsub_topic" "jobs_dlq" {
  name = "x-unfurls-jobs-dlq"

  message_retention_duration = "1209600s" # 14 days

  depends_on = [google_project_service.pubsub]
}

# =============================================================================
# Pub/Sub Push Subscription
# =============================================================================

resource "google_pubsub_subscription" "jobs_push" {
  name  = "x-unfurls-jobs-push"
  topic = google_pubsub_topic.jobs.id

  push_config {
    push_endpoint = "${google_cloud_run_v2_service.worker.uri}/pubsub"

    oidc_token {
      service_account_email = google_service_account.pubsub_push_invoker.email
    }

    attributes = {
      x-goog-version = "v1"
    }
  }

  ack_deadline_seconds = 300 # 5 minutes for xAI calls

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.jobs_dlq.id
    max_delivery_attempts = 5
  }

  message_retention_duration = "604800s"

  expiration_policy {
    ttl = "" # Never expire
  }

  depends_on = [
    google_cloud_run_v2_service.worker,
    google_cloud_run_v2_service_iam_binding.worker_invoker,
  ]
}

resource "google_pubsub_subscription" "jobs_dlq_pull" {
  name  = "x-unfurls-jobs-dlq-pull"
  topic = google_pubsub_topic.jobs_dlq.id

  ack_deadline_seconds       = 60
  message_retention_duration = "1209600s"

  expiration_policy {
    ttl = ""
  }
}
