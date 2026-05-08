provider "google" {
  project      = var.project_id
  region       = var.region
  access_token = var.static_validation_mode ? "static-validation-token" : null
}
