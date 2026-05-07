FROM mcr.microsoft.com/devcontainers/base:ubuntu

# Install system dependencies and Python tooling used by the benchmark scripts.
RUN apt-get update && apt-get install -y \
    ca-certificates \
    curl \
    gnupg \
    python3 \
    python3-pip \
    python3-venv \
    unzip \
 && rm -rf /var/lib/apt/lists/*

# Bootstrap the Python packages used for local benchmark extraction and reporting.
RUN python3 -m pip install --no-cache-dir --break-system-packages \
    google-cloud-bigquery \
    pandas
