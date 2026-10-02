terraform {
  required_version = ">= 1.10" # the S3 backend's use_lockfile, below, needs it

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.80"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.6"
    }
  }

  # State is kept locally by default. It contains generated secrets (the
  # database password, the master key), so for anything shared, move it to
  # an encrypted S3 bucket:
  #
  # backend "s3" {
  #   bucket       = "your-terraform-state"
  #   key          = "paritylens/terraform.tfstate"
  #   region       = "ap-northeast-1"
  #   encrypt      = true
  #   use_lockfile = true
  # }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = "paritylens"
      ManagedBy = "terraform"
    }
  }
}
