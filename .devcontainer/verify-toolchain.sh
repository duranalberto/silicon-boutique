#!/usr/bin/env bash
set -euo pipefail

required_tools=(terraform kubectl helm python3 minikube docker)

EXPECTED_TERRAFORM_VERSION="${EXPECTED_TERRAFORM_VERSION:-1.15.2}"
EXPECTED_KUBECTL_VERSION="${EXPECTED_KUBECTL_VERSION:-1.36.0}"
EXPECTED_HELM_VERSION="${EXPECTED_HELM_VERSION:-4.1.4}"
EXPECTED_MINIKUBE_VERSION="${EXPECTED_MINIKUBE_VERSION:-1.38.1}"

require_tool() {
  local tool="$1"

  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Missing required tool: $tool" >&2
    exit 1
  fi
}

require_version() {
  local tool="$1"
  local actual="$2"
  local expected="$3"

  if [ -n "$expected" ] && [ "$actual" != "$expected" ]; then
    echo "$tool version drift: expected $expected, found $actual" >&2
    exit 1
  fi

  echo "$tool $actual"
}

for tool in "${required_tools[@]}"; do
  require_tool "$tool"
done

terraform_version="$(terraform version -json | python3 -c 'import json, sys; print(json.load(sys.stdin)["terraform_version"])')"
kubectl_version="$(kubectl version --client=true --output=json | python3 -c 'import json, sys; print(json.load(sys.stdin)["clientVersion"]["gitVersion"].lstrip("v"))')"
helm_version="$(helm version --short | sed -E 's/^v//; s/[+ ].*$//')"
minikube_version="$(minikube version --short | sed -E 's/^v//')"

require_version "Terraform" "$terraform_version" "${EXPECTED_TERRAFORM_VERSION:-}"
require_version "kubectl" "$kubectl_version" "${EXPECTED_KUBECTL_VERSION:-}"
require_version "Helm" "$helm_version" "${EXPECTED_HELM_VERSION:-}"
require_version "minikube" "$minikube_version" "${EXPECTED_MINIKUBE_VERSION:-}"

if ! timeout "${DOCKER_INFO_TIMEOUT:-30s}" docker info >/dev/null 2>&1; then
  cat >&2 <<'EOF'
Docker is not reachable from this devcontainer.
Make sure the Docker socket is mounted and the docker-outside-of-docker feature can talk to the host daemon.
EOF
  exit 1
fi

echo "Docker is reachable."
