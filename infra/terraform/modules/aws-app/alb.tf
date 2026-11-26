# ---------------------------------------------------------------------------
# Application Load Balancer, reachable only through CloudFront.
#
# Two locks: the security group admits CloudFront's IP ranges only, and the
# listener forwards only requests carrying a secret header that our distribution
# adds. Without the header, someone else's CloudFront distribution could still
# reach the ALB, since all distributions share those IP ranges.
# ---------------------------------------------------------------------------

resource "random_password" "origin_secret" {
  length  = 32
  special = false
}

resource "aws_lb" "main" {
  #checkov:skip=CKV_AWS_150:Dev: deletion protection off so terraform destroy works.
  #checkov:skip=CKV_AWS_91:ALB access logs need a bucket and cost per request; CloudFront and app logs cover dev.
  #checkov:skip=CKV2_AWS_28:WAF is attached at CloudFront if needed, not at the ALB (Phase 7 decision).
  #checkov:skip=CKV2_AWS_20:HTTP only between CloudFront and the ALB; viewers get HTTPS from CloudFront (no domain or certificate in dev, ADR 0015).
  name               = var.name
  load_balancer_type = "application"
  internal           = false
  subnets            = aws_subnet.public[*].id
  security_groups    = [aws_security_group.alb.id]

  drop_invalid_header_fields = true
  # Answers stream over SSE; give slow generations room before the ALB closes an idle connection.
  idle_timeout = 120
}

resource "aws_lb_target_group" "web" {
  #checkov:skip=CKV_AWS_378:HTTP from the ALB to the task inside the VPC; TLS ends at CloudFront in dev (ADR 0015).
  name        = "${var.name}-web"
  vpc_id      = aws_vpc.main.id
  target_type = "ip" # Fargate tasks register by IP
  protocol    = "HTTP"
  port        = 8080

  # nginx answers /healthz itself; a database pause doesn't fail it (same rule as
  # Kubernetes liveness: never restart the front end because a dependency is slow).
  health_check {
    path                = "/healthz"
    matcher             = "200"
    interval            = 15
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  deregistration_delay = 30
}

resource "aws_lb_listener" "http" {
  #checkov:skip=CKV_AWS_2:Viewers reach HTTPS at CloudFront; the ALB only accepts CloudFront (SG prefix list + secret header). ADR 0015.
  #checkov:skip=CKV_AWS_103:No TLS listener on the ALB in dev (see CKV_AWS_2 above).
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      message_body = "Forbidden"
      status_code  = "403"
    }
  }
}

resource "aws_lb_listener_rule" "from_cloudfront" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 10

  condition {
    http_header {
      http_header_name = "X-Origin-Verify"
      values           = [random_password.origin_secret.result]
    }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}
