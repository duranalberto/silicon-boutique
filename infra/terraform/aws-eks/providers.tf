provider "aws" {
  region = var.region

  access_key = var.static_validation_mode ? "static-validation-access-key" : null
  secret_key = var.static_validation_mode ? "static-validation-secret-key" : null
  token      = var.static_validation_mode ? "static-validation-session-token" : null

  skip_credentials_validation = var.static_validation_mode
  skip_metadata_api_check     = var.static_validation_mode
  skip_region_validation      = var.static_validation_mode
  skip_requesting_account_id  = var.static_validation_mode
}
