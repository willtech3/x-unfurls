# =============================================================================
# Cloud Run Worker Service (Private - only Pub/Sub can invoke)
# =============================================================================

resource "google_cloud_run_v2_service" "worker" {
  name     = "x-unfurls-worker"
  location = var.region

  deletion_protection = false

  ingress = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  template {
    service_account = google_service_account.worker_runtime.email

    max_instance_request_concurrency = 1 # Process one job per instance

    scaling {
      min_instance_count = 1
      max_instance_count = 3
    }

    timeout = "300s" # 5 minutes for xAI calls

    containers {
      image = var.worker_image

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
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
        name = "XAI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.xai_api_key.secret_id
            version = "latest"
          }
        }
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
        period_seconds        = 5
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
    google_secret_manager_secret_iam_member.worker_secret_access,
  ]
}

resource "google_cloud_run_v2_service_iam_binding" "worker_invoker" {
  project  = var.project_id
  location = google_cloud_run_v2_service.worker.location
  name     = google_cloud_run_v2_service.worker.name
  role     = "roles/run.invoker"
  members  = ["serviceAccount:${google_service_account.pubsub_push_invoker.email}"]
}
