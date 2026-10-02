# Security groups: who may talk to whom.
#
#   internet ──443──▶ alb ──3000──▶ web ──8000──▶ api ──5432──▶ database
#                      └────8000──────────────────▶ api
#                                   worker ──8000──▶ demo APIs
#                                   worker ──5432──▶ database
#
# Rules are separate resources that name their source group, so the
# allowed paths can be read off one by one.

resource "aws_security_group" "alb" {
  name_prefix = "${var.name}-alb-"
  description = "Load balancer: HTTPS from the internet"
  vpc_id      = aws_vpc.main.id
}

resource "aws_security_group" "web" {
  name_prefix = "${var.name}-web-"
  description = "Next.js tasks"
  vpc_id      = aws_vpc.main.id
}

resource "aws_security_group" "api" {
  name_prefix = "${var.name}-api-"
  description = "API tasks"
  vpc_id      = aws_vpc.main.id
}

resource "aws_security_group" "worker" {
  name_prefix = "${var.name}-worker-"
  description = "Worker tasks: the only ones that call the APIs under test"
  vpc_id      = aws_vpc.main.id
}

resource "aws_security_group" "demo" {
  name_prefix = "${var.name}-demo-"
  description = "Demo shop APIs"
  vpc_id      = aws_vpc.main.id
}

resource "aws_security_group" "database" {
  name_prefix = "${var.name}-db-"
  description = "PostgreSQL"
  vpc_id      = aws_vpc.main.id
}

# --- inbound ---------------------------------------------------------------

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTPS from anywhere"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTP, only to be redirected to HTTPS"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}

resource "aws_vpc_security_group_ingress_rule" "web_from_alb" {
  security_group_id            = aws_security_group.web.id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = 3000
  to_port                      = 3000
}

resource "aws_vpc_security_group_ingress_rule" "api_from_alb" {
  security_group_id            = aws_security_group.api.id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}

resource "aws_vpc_security_group_ingress_rule" "api_from_web" {
  security_group_id            = aws_security_group.api.id
  referenced_security_group_id = aws_security_group.web.id
  description                  = "Server Components fetch from the API"
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}

resource "aws_vpc_security_group_ingress_rule" "demo_from_worker" {
  security_group_id            = aws_security_group.demo.id
  referenced_security_group_id = aws_security_group.worker.id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}

resource "aws_vpc_security_group_ingress_rule" "database_from_api" {
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = aws_security_group.api.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_vpc_security_group_ingress_rule" "database_from_worker" {
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = aws_security_group.worker.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

# --- outbound --------------------------------------------------------------

resource "aws_vpc_security_group_egress_rule" "alb_to_web" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.web.id
  ip_protocol                  = "tcp"
  from_port                    = 3000
  to_port                      = 3000
}

resource "aws_vpc_security_group_egress_rule" "alb_to_api" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.api.id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}

# Every task needs HTTPS out: to pull its image, read its secrets, and
# write its logs. Without a NAT gateway or VPC endpoints these are public
# AWS endpoints. For the worker this is also the path to the model provider.
resource "aws_vpc_security_group_egress_rule" "https_out" {
  for_each = {
    web    = aws_security_group.web.id
    api    = aws_security_group.api.id
    worker = aws_security_group.worker.id
    demo   = aws_security_group.demo.id
  }

  security_group_id = each.value
  description       = "HTTPS to AWS APIs and the image registry"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "web_to_api" {
  security_group_id            = aws_security_group.web.id
  referenced_security_group_id = aws_security_group.api.id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}

resource "aws_vpc_security_group_egress_rule" "api_to_database" {
  security_group_id            = aws_security_group.api.id
  referenced_security_group_id = aws_security_group.database.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_vpc_security_group_egress_rule" "worker_to_database" {
  security_group_id            = aws_security_group.worker.id
  referenced_security_group_id = aws_security_group.database.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

# A second layer under the application's EgressPolicy, and a partial one.
# Inside the VPC the worker can reach the demo APIs and the database and
# nothing else, whatever the application does. Two things it does not cover:
#
# - Port 443 is open to the internet (the model provider, ECR and Secrets
#   Manager are there), so the network does not confine HTTPS requests.
# - Security groups do not filter the link-local metadata endpoints
#   (169.254.169.254, 169.254.170.2). Those are refused by the engine,
#   which never connects to link-local addresses, and would yield nothing
#   useful: the worker's task role has no permissions.
resource "aws_vpc_security_group_egress_rule" "worker_to_demo" {
  security_group_id            = aws_security_group.worker.id
  referenced_security_group_id = aws_security_group.demo.id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}
