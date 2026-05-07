#!/usr/bin/env bash
set -euo pipefail

PROFILE="${MINIKUBE_PROFILE:-siliconboutique}"
DRIVER="${MINIKUBE_DRIVER:-docker}"
START_TIMEOUT="${MINIKUBE_START_TIMEOUT:-10m}"
STATUS_TIMEOUT="${MINIKUBE_STATUS_TIMEOUT:-30s}"
KUBERNETES_VERSION="${MINIKUBE_KUBERNETES_VERSION:-v1.35.1}"
BASE_IMAGE="${MINIKUBE_BASE_IMAGE:-docker.io/kicbase/stable:v0.0.50}"
LISTEN_ADDRESS="${MINIKUBE_LISTEN_ADDRESS:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
START_OUTPUT_FILE=""

cleanup() {
  if [ -n "$START_OUTPUT_FILE" ]; then
    rm -f "$START_OUTPUT_FILE"
  fi
}

trap cleanup EXIT

start_profile() {
  local start_args
  local start_status

  cleanup
  START_OUTPUT_FILE="$(mktemp)"
  echo "Starting local minikube profile '$PROFILE' with driver '$DRIVER'..."
  start_args=(--driver="$DRIVER" --profile="$PROFILE")
  if [ -n "$KUBERNETES_VERSION" ]; then
    start_args+=(--kubernetes-version="$KUBERNETES_VERSION")
  fi
  if [ -n "$BASE_IMAGE" ]; then
    start_args+=(--base-image="$BASE_IMAGE")
  fi
  if [ -n "$LISTEN_ADDRESS" ]; then
    start_args+=(--listen-address="$LISTEN_ADDRESS")
  fi

  set +e
  timeout "$START_TIMEOUT" minikube start "${start_args[@]}" 2>&1 | tee "$START_OUTPUT_FILE"
  start_status="${PIPESTATUS[0]}"
  set -e

  if [ "$start_status" -eq 0 ]; then
    return 0
  fi

  if [ "$start_status" -eq 124 ]; then
    echo "Timed out after $START_TIMEOUT while starting minikube profile '$PROFILE'." >&2
  fi

  return "$start_status"
}

profile_status() {
  timeout "$STATUS_TIMEOUT" minikube status --profile="$PROFILE" 2>&1
}

has_unreadable_config() {
  grep -Eqi 'HOST_CONFIG_LOAD|Unable to load config|Error getting cluster config|unmarshal'
}

"$SCRIPT_DIR/verify-toolchain.sh"

PROFILE_CONFIG="$HOME/.minikube/profiles/$PROFILE/config.json"
if [ -f "$PROFILE_CONFIG" ]; then
  configured_driver="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get("Driver", ""))' "$PROFILE_CONFIG")"
  configured_kubernetes="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get("KubernetesConfig", {}).get("KubernetesVersion", ""))' "$PROFILE_CONFIG")"
  configured_base_image="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get("KicBaseImage", ""))' "$PROFILE_CONFIG")"
  configured_listen_address="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get("ListenAddress", ""))' "$PROFILE_CONFIG")"

  if [ "$configured_driver" != "$DRIVER" ] \
    || { [ -n "$KUBERNETES_VERSION" ] && [ "$configured_kubernetes" != "$KUBERNETES_VERSION" ]; } \
    || { [ -n "$BASE_IMAGE" ] && [ "$configured_base_image" != "$BASE_IMAGE" ]; } \
    || [ "$configured_listen_address" != "$LISTEN_ADDRESS" ]; then
    echo "Local minikube profile '$PROFILE' does not match the devcontainer baseline."
    echo "Deleting and recreating only the '$PROFILE' profile..."
    minikube delete --profile="$PROFILE" || true
  fi
fi

if profile_status >/dev/null; then
  echo "Local minikube profile '$PROFILE' is already available."
else
  status_output="$(profile_status || true)"
  if has_unreadable_config <<<"$status_output"; then
    echo "Local minikube profile '$PROFILE' has an unreadable config."
    echo "Deleting and recreating only the '$PROFILE' profile..."
    minikube delete --profile="$PROFILE" || true
    start_profile
  elif ! start_profile; then
    if has_unreadable_config <"$START_OUTPUT_FILE"; then
      echo "Local minikube profile '$PROFILE' has an unreadable config."
      echo "Deleting and recreating only the '$PROFILE' profile..."
      minikube delete --profile="$PROFILE" || true
      start_profile
    else
      exit 1
    fi
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
