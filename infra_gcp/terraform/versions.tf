terraform {
  required_version = ">= 1.6.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = ">= 5.0.0"
    }
  }

  # Remote state stored in GCS for CI/CD
  # Bucket must be created before first terraform init (see DEPLOYMENT.md Phase 2.3)
  backend "gcs" {
    # Configured via -backend-config in CI/CD:
    #   bucket = "${PROJECT_ID}-terraform-state"
    #   prefix = "x-unfurls"
  }
}
