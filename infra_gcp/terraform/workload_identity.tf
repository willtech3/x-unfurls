# =============================================================================
# Workload Identity Pool for GitHub Actions
# =============================================================================

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github-actions-pool"
  display_name              = "GitHub Actions Pool"
  description               = "Workload Identity Pool for GitHub Actions CI/CD"

  depends_on = [
    google_project_service.iam,
    google_project_service.iamcredentials,
    google_project_service.sts,
  ]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-provider"
  display_name                       = "GitHub Actions OIDC Provider"
  description                        = "OIDC identity provider for GitHub Actions workflows"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.aud"        = "assertion.aud"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }

  # SECURITY: Use repository_owner_id (numeric) to prevent squatting attacks
  attribute_condition = <<-EOT
    assertion.repository_owner_id == "${var.github_repo_owner_id}" &&
    attribute.repository == "${var.github_repo_owner}/${var.github_repo_name}" &&
    attribute.ref == "refs/heads/main"
  EOT

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# =============================================================================
# CI/CD Service Account
# =============================================================================

resource "google_service_account" "cicd" {
  account_id   = "x-unfurls-cicd"
  display_name = "X Unfurls - CI/CD"
  description  = "Service account for GitHub Actions deployments"

  depends_on = [google_project_service.iam]
}

resource "google_service_account_iam_member" "cicd_workload_identity" {
  service_account_id = google_service_account.cicd.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo_owner}/${var.github_repo_name}"
}

# =============================================================================
# CI/CD Permissions
# =============================================================================

resource "google_artifact_registry_repository_iam_member" "cicd_writer" {
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.x_unfurls.repository_id
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.cicd.email}"
}

resource "google_project_iam_member" "cicd_run_developer" {
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.cicd.email}"
}

resource "google_service_account_iam_member" "cicd_act_as_webhook" {
  service_account_id = google_service_account.webhook_runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.cicd.email}"
}

resource "google_service_account_iam_member" "cicd_act_as_worker" {
  service_account_id = google_service_account.worker_runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.cicd.email}"
}
