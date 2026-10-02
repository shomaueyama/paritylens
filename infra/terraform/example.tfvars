# Copy to terraform.tfvars (which is not committed) and fill in.

region            = "ap-northeast-1"
domain_name       = "paritylens.example.com"
certificate_arn   = "arn:aws:acm:ap-northeast-1:123456789012:certificate/00000000-0000-0000-0000-000000000000"
github_repository = "your-account/paritylens"

google_client_id = "000000000000-example.apps.googleusercontent.com"

# Pass secrets through the environment instead of writing them in a file:
#   export TF_VAR_google_client_secret=...
#   export TF_VAR_anthropic_api_key=...     (optional: enables AI analysis)
