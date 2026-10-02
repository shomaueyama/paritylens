# One image repository per image. The API, the worker and the demo APIs
# are built from one Dockerfile with different arguments.

locals {
  images = toset(["api", "web", "legacy-shop-api", "modern-shop-api"])
}

resource "aws_ecr_repository" "app" {
  for_each = local.images

  name                 = "${var.name}/${each.key}"
  image_tag_mutability = "IMMUTABLE" # a tag, once pushed, always means the same image
  force_delete         = var.allow_destroy

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  for_each = aws_ecr_repository.app

  repository = each.value.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 20 most recent images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 20
      }
      action = { type = "expire" }
    }]
  })
}
