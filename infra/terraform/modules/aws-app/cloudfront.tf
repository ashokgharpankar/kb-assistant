# ---------------------------------------------------------------------------
# CloudFront: HTTPS for viewers on *.cloudfront.net, with AWS's certificate, so no
# domain is needed. Cognito only accepts HTTPS callback URLs (except localhost).
# Caching is off: the UI is small, /config.json must stay fresh, and /api/ is
# per-user and streams (SSE).
# ---------------------------------------------------------------------------

data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

# Forwards every viewer header (including Authorization for the API) except Host,
# so the ALB sees its own host name.
data "aws_cloudfront_origin_request_policy" "all_viewer" {
  name = "Managed-AllViewerExceptHostHeader"
}

resource "aws_cloudfront_distribution" "main" {
  #checkov:skip=CKV_AWS_374:No geo restriction: sign-in is invite-only (Cognito), so access is controlled per user, not per country.
  #checkov:skip=CKV_AWS_68:WAF on CloudFront is a Phase 7 decision (rate limiting, bot control); ~$5/month + rules.
  #checkov:skip=CKV_AWS_86:CloudFront access logs need a bucket; not needed in dev.
  #checkov:skip=CKV_AWS_310:No origin failover: one origin in dev.
  #checkov:skip=CKV_AWS_174:The default *.cloudfront.net certificate fixes the minimum TLS version; set TLSv1.2_2021 when a custom domain and ACM certificate exist.
  #checkov:skip=CKV2_AWS_32:Security headers (CSP, HSTS…) are set by nginx in the web container (Phase 6a), so they are the same locally and in AWS.
  #checkov:skip=CKV2_AWS_47:Log4j rule set is a WAF feature; no WAF in dev (see CKV_AWS_68).
  #checkov:skip=CKV2_AWS_42:Custom domain and ACM certificate not used in dev (ADR 0015).
  #checkov:skip=CKV_AWS_305:The SPA is served by nginx at /; no default root object needed.
  enabled         = true
  comment         = var.name
  is_ipv6_enabled = true
  http_version    = "http2and3"
  price_class     = "PriceClass_100" # North America and Europe edge locations: cheapest

  origin {
    origin_id   = "alb"
    domain_name = aws_lb.main.dns_name

    custom_origin_config {
      http_port                = 80
      https_port               = 443
      origin_protocol_policy   = "http-only"
      origin_ssl_protocols     = ["TLSv1.2"]
      origin_read_timeout      = 60 # max without a quota increase; SSE sends tokens well within it
      origin_keepalive_timeout = 60
    }

    custom_header {
      name  = "X-Origin-Verify"
      value = random_password.origin_secret.result
    }
  }

  default_cache_behavior {
    target_origin_id         = "alb"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer.id
    compress                 = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}
