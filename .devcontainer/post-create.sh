#!/usr/bin/env bash
set -euo pipefail

PROFILE="${MINIKUBE_PROFILE:-siliconboutique}"
DRIVER="${MINIKUBE_DRIVER:-docker}"
START_TIMEOUT="${MINIKUBE_START_TIMEOUT:-10m}"
required_tools=(terraform kubectl helm python3 minikube docker)

start_profile() {
  echo "Starting local minikube profile '$PROFILE' with driver '$DRIVER'..."
  if timeout "$START_TIMEOUT" minikube start --driver="$DRIVER" --profile="$PROFILE"; then
    return 0
  else
    start_status=$?
    if [ "$start_status" -eq 124 ]; then
      echo "Timed out after $START_TIMEOUT while starting minikube profile '$PROFILE'." >&2
    fi
    return "$start_status"
  fi
}

for tool in "${required_tools[@]}"; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Missing required tool: $tool" >&2
    exit 1
  fi
done

if ! docker info >/dev/null 2>&1; then
  cat >&2 <<'EOF'
Docker is not reachable from this devcontainer.
Make sure the Docker socket is mounted and the docker-outside-of-docker feature can talk to the host daemon.
EOF
  exit 1
fi

if minikube status --profile="$PROFILE" >/dev/null 2>&1; then
  echo "Local minikube profile '$PROFILE' is already available."
else
  status_output="$(minikube status --profile="$PROFILE" 2>&1 || true)"
  if grep -Eqi 'HOST_CONFIG_LOAD|Unable to load config|Error getting cluster config|unmarshal' <<<"$status_output"; then
    echo "Local minikube profile '$PROFILE' has an unreadable config."
    echo "Deleting and recreating only the '$PROFILE' profile..."
    minikube delete --profile="$PROFILE" || true
    start_profile
  elif ! start_output="$(start_profile 2>&1)"; then
    printf '%s\n' "$start_output" >&2
    if grep -Eqi 'HOST_CONFIG_LOAD|Unable to load config|Error getting cluster config|unmarshal' <<<"$start_output"; then
      echo "Local minikube profile '$PROFILE' has an unreadable config."
      echo "Deleting and recreating only the '$PROFILE' profile..."
      minikube delete --profile="$PROFILE" || true
      start_profile
    else
      exit 1
    fi
  else
    printf '%s\n' "$start_output"
  fi
fi

echo "Updating kubeconfig for profile '$PROFILE'..."
minikube update-context --profile="$PROFILE" >/dev/null

echo "Waiting for the local Kubernetes cluster to become ready..."
for _ in $(seq 1 30); do
  if kubectl get nodes --no-headers 2>/dev/null | awk '$2 == "Ready" { found=1 } END { exit found ? 0 : 1 }'; then
    echo "Local Kubernetes validation path is ready."
    kubectl config current-context
    exit 0
  fi
  sleep 2
done

echo "Minikube started, but the Kubernetes control plane did not become ready in time." >&2
minikube status --profile="$PROFILE" >&2 || true
kubectl cluster-info >&2 || true
exit 1
