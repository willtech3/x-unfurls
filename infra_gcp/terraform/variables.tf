variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region for resources"
  type        = string
  default     = "us-central1"
}

variable "github_repo_owner" {
  description = "GitHub repository owner (organization or username)"
  type        = string
}

variable "github_repo_name" {
  description = "GitHub repository name"
  type        = string
  default     = "x-unfurls"
}

variable "github_repo_owner_id" {
  description = "GitHub repository owner ID (numeric). Find via: gh api users/OWNER --jq .id"
  type        = string
}

variable "webhook_image" {
  description = "Full image path for webhook service"
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello" # Placeholder
}

variable "worker_image" {
  description = "Full image path for worker service"
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello" # Placeholder
}
