# =============================================================================
# Cloud Run Webhook Service (Public - accessible by Slack)
# =============================================================================

resource "google_cloud_run_v2_service" "webhook" {
  provider = google-beta
  name     = "x-unfurls-webhook"
  location = var.region

  invoker_iam_disabled = true # Allow Slack to call without Google auth

  ingress = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.webhook_runtime.email

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    containers {
      image = var.webhook_image

      resources {
        limits = {
          cpu    = "1"
          memory = "256Mi"
        }
        cpu_idle = true
      }

      ports {
        container_port = 8080
      }

      env {
        name = "SLACK_BOT_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.slack_bot_token.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "SLACK_SIGNING_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.slack_signing_secret.secret_id
            version = "latest"
          }
        }
      }

      env {
        name  = "PUBSUB_TOPIC"
        value = google_pubsub_topic.jobs.name
      }

      env {
        name  = "PUBSUB_PROJECT"
        value = var.project_id
      }

      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }

      startup_probe {
        http_get {
          path = "/health"
          port = 8080
        }
        initial_delay_seconds = 0
        timeout_seconds       = 3
        period_seconds        = 3
        failure_threshold     = 10
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [
    google_project_service.run,
    google_secret_manager_secret_iam_member.webhook_secret_access,
  ]
}
