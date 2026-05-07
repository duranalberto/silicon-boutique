#!/usr/bin/env bash
set -euo pipefail

required_tools=(terraform kubectl helm python3 minikube)

for tool in "${required_tools[@]}"; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Missing required tool: $tool" >&2
    exit 1
  fi
done

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  if ! minikube status --profile=siliconboutique >/dev/null 2>&1; then
    echo "Starting the local minikube profile..."
    minikube start --driver=docker --profile=siliconboutique
  else
    echo "Local minikube profile is already available."
  fi
else
  echo "Docker is not available in this environment, so local cluster bootstrap was skipped."
fi
