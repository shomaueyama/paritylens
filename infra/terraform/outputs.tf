output "load_balancer_dns_name" {
  description = "Point a CNAME (or Route 53 alias) for domain_name at this."
  value       = aws_lb.main.dns_name
}

output "deploy_role_arn" {
  description = "Set as the AWS_DEPLOY_ROLE_ARN variable of the GitHub repository."
  value       = aws_iam_role.deploy.arn
}

output "ecr_registry" {
  description = "Registry the deploy workflow pushes images to."
  value       = local.registry
}

output "google_redirect_uri" {
  description = "Register this as an authorised redirect URI of the Google OAuth client."
  value       = "${local.public_base_url}/api/v1/auth/google/callback"
}
