# ---------------------------------------------------------------------------
# Sign-in for the web UI (Phase 2c).
#
# Cognito hosts the sign-in page ("managed login") and issues tokens. The UI
# sends the access token to the API, and the API checks it locally against
# Cognito's public keys. The API needs no AWS permissions for that.
#
# Cost: the Essentials plan includes 10,000 monthly active users free, with no
# end date, for users who sign in directly (not through SAML/OIDC federation).
# ---------------------------------------------------------------------------

locals {
  # The sign-in page lives at https://<prefix>.auth.<region>.amazoncognito.com.
  # The prefix must be unique in the region. A short hash of the account ID
  # makes it unique without putting the account ID in a public URL.
  cognito_domain_prefix = "${local.name}-${substr(sha256(local.account_id), 0, 8)}"
}

resource "aws_cognito_user_pool" "main" {
  name = "${local.name}-users"

  # Essentials: managed login pages and its branding editor need it.
  user_pool_tier = "ESSENTIALS"

  # Dev: allow `terraform destroy`. In prod set "ACTIVE" so a stray destroy
  # can't delete every user account.
  deletion_protection = "INACTIVE"

  # Private app: no self sign-up. Only an admin (you) creates users, and Cognito
  # emails them a temporary password they must change at first sign-in.
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  # Users sign in with their email address.
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  username_configuration {
    case_sensitive = false
  }

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 3
  }

  # Users may add an authenticator app (TOTP). "ON" would force it for everyone.
  mfa_configuration = "OPTIONAL"

  software_token_mfa_configuration {
    enabled = true
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  # Cognito's built-in email sender: free, limited to 50 emails a day. Fine for
  # invites and password resets here; production would use Amazon SES.
  email_configuration {
    email_sending_account = "COGNITO_DEFAULT"
  }
}

resource "aws_cognito_user_pool_domain" "main" {
  domain       = local.cognito_domain_prefix
  user_pool_id = aws_cognito_user_pool.main.id

  # 2 = managed login (current pages, branding editor); 1 = classic hosted UI.
  managed_login_version = 2
}

# The web UI is a "public client": its code runs in the browser, so it can't
# keep a secret. Instead it uses the authorization code flow with PKCE: the
# browser proves it started the sign-in by revealing a one-time secret it
# generated, so a stolen authorization code is useless on its own.
resource "aws_cognito_user_pool_client" "web" {
  name         = "${local.name}-web"
  user_pool_id = aws_cognito_user_pool.main.id

  generate_secret = false

  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]

  # Where Cognito may send the browser back to. Exact matches only.
  callback_urls = var.web_app_urls
  logout_urls   = var.web_app_urls

  # Sign-in happens on the managed login page, which uses SRP (the password is
  # never sent in clear). The UI itself only refreshes tokens.
  explicit_auth_flows = ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]

  # Short-lived access tokens limit the damage if one leaks; the refresh token
  # gets a new one silently.
  access_token_validity  = 60
  id_token_validity      = 60
  refresh_token_validity = 7

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }

  # "Incorrect username or password" whether or not the user exists, so the
  # sign-in page can't be used to discover which emails have accounts.
  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true
}

# Managed login needs a style for each app client; without one the sign-in page
# shows an error. Cognito's default look is enough here.
resource "aws_cognito_managed_login_branding" "web" {
  user_pool_id                = aws_cognito_user_pool.main.id
  client_id                   = aws_cognito_user_pool_client.web.id
  use_cognito_provided_values = true
}
