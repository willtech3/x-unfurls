output "webhook_url" {
  description = "URL of the webhook Cloud Run service (configure in Slack app settings)"
  value       = google_cloud_run_v2_service.webhook.uri
}

output "worker_url" {
  description = "URL of the worker Cloud Run service (internal only)"
  value       = google_cloud_run_v2_service.worker.uri
}

