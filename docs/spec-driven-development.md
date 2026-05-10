# AI Spec Driven Development Document
## Project: SiliconBoutique
**Primary Cloud Target:** Google Cloud Platform (GCP)
**Development and Test Environment:** Local Kubernetes
**Objective:** Automated, ephemeral benchmarking of cloud processors using a standardized microservices workload ("Online Boutique") to evaluate performance and price-to-performance ratios.

---

### 1. Executive Summary & Cloud Strategy
Project SiliconBoutique transforms cloud infrastructure into an automated testing laboratory. By utilizing **Google Cloud Platform (GCP)**, specifically GKE and Spot VMs, as the first cloud rollout path while also supporting a local Kubernetes validation path for development and testing, we keep the Google-developed Online Boutique workload compatible across environments while minimizing compute costs.

This architecture supports a **Model Context Protocol (MCP)** boundary so future AI agents or LLMs can autonomously trigger benchmarks, query historical performance data, and analyze processor comparisons without human intervention.

---

### 2. Architecture Overview
The system is divided into five decoupled components. To ensure MCP readiness, all interactions between the automation layer and the metrics layer are structured and API-driven.

1. **Infrastructure Foundation:** Ephemeral Kubernetes environments provisioned via Terraform, with a local Kubernetes validation path first and GCP as the rollout target.
2. **Workload Deployment:** Helm-deployed Online Boutique services with configurable load profiles.
3. **Metrics Pipeline:** Prometheus metrics summarized into structured benchmark data and persisted in BigQuery for AI and MCP querying.
4. **Automation Workflow:** GitHub Actions orchestration that sequences provisioning, deployment, benchmark execution, extraction, and teardown.
5. **MCP Boundary:** A lightweight API and schema design allowing AI agents to consume benchmark status and historical data.

---

### 3. Component Specifications

#### Component 1: Infrastructure (The Foundation)
**Goal:** Provide a repeatable, parameterized Kubernetes environment via Infrastructure as Code (IaC).
* **Technology:** Terraform, Kubernetes, and GCP-specific modules for the cloud rollout path.
* **Requirements:**
    * Dynamic variable inputs for `machine_type`, `region`, and `node_count`.
    * Support a local Kubernetes validation path that exercises the same workload and deployment shape before GCP rollout.
    * Support for multiple architectures (e.g., `x86_64` Intel/AMD vs. `arm64` Tau T2A).
    * Strict tagging/labeling (e.g., `run_id`, `processor_family`) applied to all resources to trace billing costs accurately.
* **Output to Next Stage:** A generated `kubeconfig` and a unique `run_id`.

#### Component 2: Workload & Load Generation
**Goal:** Deploy the microservices and simulate real-world stress.
* **Technology:** Helm, Kubernetes.
* **Requirements:**
    * Deploy the standard 11 microservices from the Google microservices-demo repository.
    * **Decoupled Load Generator:** The load generation pod must accept environment variables for `USERS_PER_SECOND` and `TEST_DURATION`.
    * **Resource Constraints:** Pod requests/limits must be configured dynamically to ensure the *hardware node* hits 80-90% utilization, creating a valid bottleneck for testing.

#### Component 3: Observability & Data Lake (The Scientist)
**Goal:** Capture metrics and persist them in a highly queryable format for future AI/MCP consumption.
* **Technology:** Prometheus (kube-prometheus-stack), Grafana, Google BigQuery.
* **Requirements:**
    * Prometheus scrapes local metrics (Node CPU/RAM, Pod Throttling, P99 Latency).
    * **MCP Readiness Pivot:** Instead of leaving data in a remote-write Prometheus bucket, aggregate the results of the benchmark run and push a structured JSON payload to **BigQuery**.
    * BigQuery allows future LLMs to run complex SQL analysis via MCP (e.g., *"Compare average P99 checkout latency between c3-standard-4 and t2a-standard-4"*).

#### Component 4: Automation Orchestrator
**Goal:** End-to-end pipeline execution with zero human touch.
* **Technology:** GitHub Actions.
* **Requirements:**
    * **Provision:** `terraform apply -auto-approve -var="machine_type=$MACHINE"`
    * **Deploy:** `helm upgrade --install ...`
    * **Benchmark:** Run LoadGenerator for exactly 20 minutes.
    * **Extract:** Run a script to query Prometheus, calculate averages and percentiles, and push the final `BenchmarkSummary` to BigQuery.
    * **Teardown:** `terraform destroy -auto-approve` (Guaranteed to run via `always()` conditionals, preventing billing leaks).

---

### 4. AI / MCP Integration Design (Extensibility)

To ensure this project can be consumed by an AI agent via the Model Context Protocol, we must design the system with a clear **API boundary** and **data schema**.

We will expose the GitHub Actions workflow via the `workflow_dispatch` API, and the data via BigQuery.

#### Future MCP Server Tools to be Implemented:
When the MCP service is built, it will expose the following tools to the LLM:

1.  **`trigger_benchmark_run`**
    * *Description:* Tells the CI/CD pipeline to spin up a cluster and run a test.
    * *Input Schema:*
        ```json
        {
          "cloud_provider": "gcp",
          "machine_type": "c3-standard-4",
          "load_users_per_second": 1000
        }
        ```
    * *Implementation:* Sends a POST request to the GitHub Actions REST API. Returns a `run_id`.

2.  **`get_benchmark_status`**
    * *Description:* Checks if a benchmark run is Queued, Running, or Completed.
    * *Input Schema:* `{"run_id": "string"}`

3.  **`query_historical_metrics`**
    * *Description:* Retrieves structured performance data to compare processors.
    * *Implementation:* Wraps a parameterized BigQuery SQL execution.
    * *Output Schema:*
        ```json
        {
          "run_id": "12345",
          "machine_type": "c3-standard-4",
          "avg_cpu_utilization_pct": 82.4,
          "max_memory_used_gb": 12.1,
          "p99_latency_ms": 145,
          "cost_per_1M_requests_usd": 0.42
        }
        ```

### 5. Implementation Roadmap

[`docs/roadmap.md`](roadmap.md) is the authoritative implementation sequence for this repository. It tracks the current phase flow from repo bootstrap through production MCP integration and the behavior-preserving refactor work.
