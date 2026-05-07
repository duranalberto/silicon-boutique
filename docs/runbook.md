# Runbook

## Local Development

1. Open the repository in the devcontainer.
2. Verify the environment has Terraform, kubectl, Helm, Python, Docker, and minikube.
3. Let the devcontainer bootstrap the local `siliconboutique` minikube profile; the post-create script now checks the toolchain, verifies Docker access, and starts or validates the profile automatically.
4. Review `docs/spec-driven-development.md` and `docs/project-layout.md`.
5. Review `docs/architecture.md` and `docs/roadmap.md` for the current pipeline language and phase order.

## Benchmark Execution Flow

1. Provision the target environment with Terraform.
2. Deploy the Kubernetes workload and monitoring stack with Helm.
3. Start the benchmark run.
4. Collect metrics and produce a summary payload.
5. Teardown the infrastructure when complete.

## Cloud Rollout

1. Use GCP for the first cloud benchmark target after local validation is complete.
2. Confirm cloud credentials and Terraform state are configured before applying.
3. Run the same deployment and benchmark flow used in local Kubernetes.
4. Preserve teardown discipline to avoid leaving cloud resources running.

## Teardown Checks

- Confirm the run has finished collecting data.
- Confirm any persisted summaries have been written.
- Confirm no long-lived resources remain attached to the cluster.

## Troubleshooting

- If minikube does not start, confirm Docker is available to the devcontainer and that the Docker socket is mounted.
- If the configured minikube profile has a corrupt or unreadable config, the devcontainer bootstrap deletes and recreates only that named local profile.
- If the cloud rollout fails, recheck GCP authentication, project selection, and Terraform provider settings.
- If Terraform fails, inspect state and provider configuration first.
- If Kubernetes resources do not appear, verify the cluster context and namespace.
