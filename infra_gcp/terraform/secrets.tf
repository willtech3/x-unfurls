# Create secrets as infrastructure, populate values out-of-band via gcloud CLI

resource "google_secret_manager_secret" "slack_bot_token" {
  secret_id = "x-unfurls-slack-bot-token"

  replication {
    auto {}
  }

  depends_on = [google_project_service.secretmanager]
}

resource "google_secret_manager_secret" "slack_signing_secret" {
  secret_id = "x-unfurls-slack-signing-secret"

  replication {
    auto {}
  }

  depends_on = [google_project_service.secretmanager]
}

resource "google_secret_manager_secret" "xai_api_key" {
  secret_id = "x-unfurls-xai-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.secretmanager]
}
