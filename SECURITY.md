# Security

## Secrets

- Do not commit service account keys, tokens, kubeconfigs, or local cluster credentials.
- Keep GCP and AWS credentials in environment-managed secret stores or CI secret providers, and keep local Kubernetes access data out of tracked files.
- Rotate any exposed credential immediately.

## Infrastructure

- Treat Terraform state as sensitive.
- Treat kubeconfigs, Terraform state, cloud provider state, BigQuery access, and benchmark artifacts as sensitive for every local, GCP, and AWS path.
- Restrict access to benchmark results that may include environment details or cost data.
- Confirm teardown logic before running destructive workflows.

## Reporting

If you find a security issue, document:

- what component is affected
- the potential impact
- whether credentials or state may be exposed
- the smallest safe mitigation

Then notify the project maintainers through the private channel you normally use for this workspace.
