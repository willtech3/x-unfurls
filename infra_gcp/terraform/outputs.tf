output "artifact_registry_url" {
  description = "Artifact Registry URL for Docker images"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.x_unfurls.repository_id}"
}

output "webhook_url" {
  description = "URL of the webhook Cloud Run service (configure in Slack app settings)"
  value       = google_cloud_run_v2_service.webhook.uri
}

output "worker_url" {
  description = "URL of the worker Cloud Run service (internal only)"
  value       = google_cloud_run_v2_service.worker.uri
}

output "workload_identity_provider" {
  description = "Workload Identity Provider resource name (use in GitHub Actions auth)"
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "cicd_service_account_email" {
  description = "CI/CD service account email (use in GitHub Actions auth)"
  value       = google_service_account.cicd.email
}
