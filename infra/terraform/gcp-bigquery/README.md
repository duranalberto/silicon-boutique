# GCP BigQuery Terraform

This Terraform root provisions durable BigQuery storage for SiliconBoutique benchmark summaries. It is intentionally separate from `infra/terraform/gcp-gke` because benchmark history must survive run-scoped GKE teardown.

Routine validation is bounded and does not create cloud resources:

```bash
timeout 20s terraform fmt -check -recursive
timeout 60s terraform init -backend=false -input=false
timeout 30s terraform validate
timeout 60s terraform plan -refresh=false -input=false -var='project_id=example-project'
```

Apply only after confirming the project, credentials, dataset location, and retention expectations:

```bash
timeout 10m terraform plan -input=false \
  -var='project_id=<project-id>' \
  -var='summary_writer_service_accounts=["<github-actions-service-account>@<project-id>.iam.gserviceaccount.com"]' \
  -var='static_validation_mode=false'

timeout 10m terraform apply -auto-approve \
  -var='project_id=<project-id>' \
  -var='summary_writer_service_accounts=["<github-actions-service-account>@<project-id>.iam.gserviceaccount.com"]' \
  -var='static_validation_mode=false'
```

The default destination is `<project-id>.silicon_boutique.benchmark_summaries` in location `US`. When `summary_writer_service_accounts` is set, Terraform grants each service account `roles/bigquery.jobUser` on the project and `roles/bigquery.dataEditor` on the durable dataset so the benchmark workflow can run load jobs and write the summary table. These resources are not run-scoped, do not carry teardown labels, and should not be destroyed as part of benchmark cleanup.
