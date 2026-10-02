# One load balancer, one hostname. Requests under /api/ go to the API,
# everything else to the web app. The browser therefore sees a single
# origin, which is what the session cookie and the Origin check assume.

resource "aws_lb" "main" {
  name_prefix        = substr(var.name, 0, 6)
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  drop_invalid_header_fields = true
}

resource "aws_lb_target_group" "web" {
  name_prefix = "web-"
  vpc_id      = aws_vpc.main.id
  port        = 3000
  protocol    = "HTTP"
  target_type = "ip" # Fargate tasks are addressed by IP, not by instance

  health_check {
    path    = "/login"
    matcher = "200"
  }

  deregistration_delay = 30
}

resource "aws_lb_target_group" "api" {
  name_prefix = "api-"
  vpc_id      = aws_vpc.main.id
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"

  health_check {
    path    = "/api/v1/health"
    matcher = "200"
  }

  deregistration_delay = 30
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}

resource "aws_lb_listener_rule" "api" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 10

  condition {
    path_pattern {
      values = ["/api/*"]
    }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}
