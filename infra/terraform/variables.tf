variable "region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "ap-northeast-1"
}

variable "name" {
  description = "Prefix for resource names."
  type        = string
  default     = "paritylens"
}

variable "domain_name" {
  description = "Public hostname of the application, e.g. paritylens.example.com. Session cookies are Secure, so the site must be served over HTTPS under a real name."
  type        = string
}

variable "certificate_arn" {
  description = "ARN of an ACM certificate for domain_name, in the same region."
  type        = string
}

variable "image_tag" {
  description = "Tag of the container images to run. The deploy workflow pushes images under the commit SHA."
  type        = string
  default     = "latest"
}

variable "github_repository" {
  description = "owner/name of the GitHub repository allowed to deploy, e.g. shomaueyama/paritylens."
  type        = string
}

variable "google_client_id" {
  description = "OAuth client ID for Sign in with Google."
  type        = string
}

variable "google_client_secret" {
  description = "OAuth client secret for Sign in with Google."
  type        = string
  sensitive   = true
}

variable "anthropic_api_key" {
  description = "API key for AI analysis. Leave empty to deploy without it."
  type        = string
  default     = ""
  sensitive   = true
}

variable "github_oidc_provider_arn" {
  description = "ARN of the account's existing IAM OIDC provider for token.actions.githubusercontent.com. An account can have only one; leave empty to create it here."
  type        = string
  default     = ""
}

variable "desired_count" {
  description = "Tasks per service. Set to 0 to stop everything without destroying it."
  type        = number
  default     = 1

  validation {
    # Migrations run when the API task starts; two starting at once would race.
    condition     = contains([0, 1], var.desired_count)
    error_message = "This configuration is written for one task per service."
  }
}

variable "allow_destroy" {
  description = "Lets terraform destroy remove what holds data: the database (deletion protection off) and image repositories that still contain images."
  type        = bool
  default     = false
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.micro"
}

locals {
  public_base_url = "https://${var.domain_name}"
  ai_enabled      = var.anthropic_api_key != ""

  # The demo APIs, reachable only from inside the VPC. The public
  # deployment runs in allowlist mode and may call nothing else.
  demo_services = {
    legacy-shop-api = "legacy_shop_api.main:app"
    modern-shop-api = "modern_shop_api.main:app"
  }
  egress_allow_hosts = join(",", [for name in keys(local.demo_services) : "${name}:8000"])
}
