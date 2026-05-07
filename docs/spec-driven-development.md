# AI Spec Driven Development Document
## Project: SiliconBoutique
**Primary Cloud Target:** Google Cloud Platform (GCP)
**Development and Test Environment:** Local Kubernetes
**Objective:** Automated, ephemeral benchmarking of cloud processors using a standardized microservices workload ("Online Boutique") to evaluate performance and price-to-performance ratios.

---

### 1. Executive Summary & Cloud Strategy
Project SiliconBoutique transforms cloud infrastructure into an automated testing laboratory. By utilizing **Google Cloud Platform (GCP)**—specifically GKE and Spot VMs—as the first cloud target, while also supporting local Kubernetes for development and testing, we achieve native compatibility with the Google-developed Online Boutique workload while minimizing compute costs by up to 90%.

This architecture supports a **Model Context Protocol (MCP)** integration layer so future AI agents or LLMs can autonomously trigger benchmarks, query historical performance data, and analyze processor comparisons without human intervention.

---

### 2. Architecture Overview
The system is divided into five decoupled components. To ensure MCP readiness, all interactions between the automation layer and the data layer are heavily structured and API-driven.

1. **Infrastructure Foundation:** Ephemeral Kubernetes environments provisioned via Terraform, with GKE as the first cloud target.
2. **Workload Generator:** Helm-deployed microservices with configurable load profiles.
3. **Observability & Data Lake:** Short-term Prometheus metrics exported to a persistent BigQuery data lake (Crucial for AI/MCP querying).
4. **Automation Engine:** GitHub Actions for orchestration, exposing RESTful workflow triggers.
5. **Control Plane / MCP Interface (Future-Proofing):** A lightweight API/schema design allowing AI agents to consume the system.

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
    * **MCP Readiness Pivot:** Instead of leaving data in a remote-write Prometheus bucket, aggregate the results of the 20-minute run and push a structured JSON payload to **BigQuery**. 
    * BigQuery allows future LLMs to run complex SQL analysis via MCP (e.g., *"Compare average P99 checkout latency between c3-standard-4 and t2a-standard-4"*).

#### Component 4: Automation Orchestrator
**Goal:** End-to-end pipeline execution with zero human touch.
* **Technology:** GitHub Actions (or GitLab CI).
* **Requirements:**
    * **Phase 1 (Setup):** `terraform apply -auto-approve -var="machine_type=$MACHINE"`
    * **Phase 2 (Deploy):** `helm upgrade --install ...`
    * **Phase 3 (Test):** Run LoadGenerator for exactly 20 minutes.
    * **Phase 4 (Extract):** Run a script to query Prometheus, calculate averages/percentiles, and push the final `BenchmarkSummary` to BigQuery.
    * **Phase 5 (Teardown):** `terraform destroy -auto-approve` (Guaranteed to run via `always()` conditionals, preventing billing leaks).

---

### 4. AI / MCP Integration Design (Extensibility)

To ensure this project can be consumed by an AI agent via the Model Context Protocol, we must design the system with a clear **API Boundary** and **Data Schema**. 

We will expose the GitHub Actions via the `workflow_dispatch` API, and the data via BigQuery.

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

* **Phase 1: Local Proof of Concept**
    * Make the devcontainer a usable local benchmark environment.
    * Verify Helm deploys correctly against a local Kubernetes cluster such as minikube.
* **Phase 2: Pipeline Automation**
    * Write the GitHub Actions YAML.
    * Ensure robust state management (GCS backend for Terraform) so `destroy` never fails.
* **Phase 3: Data Engineering & MCP Prep**
    * Write the Python extraction script (Phase 4 of CI/CD) that pulls Prometheus metrics, formats them into the JSON schema defined above, and inserts them into BigQuery.
* **Phase 4: MCP Server Implementation**
    * Write a lightweight Python or Node.js MCP server that securely holds the GitHub PAT and GCP Service Account credentials, exposing the three tools defined in Section 4.
