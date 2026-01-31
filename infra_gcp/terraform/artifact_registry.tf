resource "google_artifact_registry_repository" "x_unfurls" {
  location      = var.region
  repository_id = "x-unfurls"
  format        = "DOCKER"
  description   = "Docker images for X Unfurls application"

  # Cleanup policy to stay within free tier (0.5 GB)
  cleanup_policy_dry_run = false
  cleanup_policies {
    id     = "keep-recent-versions"
    action = "KEEP"
    most_recent_versions {
      keep_count = 3
    }
  }

  depends_on = [google_project_service.artifactregistry]
}
