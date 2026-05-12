import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
AWS_ROOT = REPO_ROOT / "infra" / "terraform" / "aws-eks"
PRICING = REPO_ROOT / "automation" / "templates" / "machine-pricing.json"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "benchmark-aws.yml"


class AwsEksScaffoldTest(unittest.TestCase):
    def read(self, name):
        return (AWS_ROOT / name).read_text(encoding="utf-8")

    def test_terraform_root_exposes_required_metadata_contract(self):
        variables = self.read("variables.tf")
        outputs = self.read("outputs.tf")
        required_variables = (
            "run_id",
            "environment",
            "region",
            "zone",
            "machine_type",
            "node_count",
            "processor_family",
            "cpu_platform",
            "architecture",
            "pricing_model",
            "enable_spot_nodes",
            "cluster_version",
            "disk_size_gb",
        )
        required_outputs = (
            "run_id",
            "environment",
            "cloud_provider",
            "region",
            "zone",
            "machine_type",
            "processor_family",
            "cpu_platform",
            "architecture",
            "node_count",
            "pricing_model",
            "get_credentials_command",
            "tags",
            "node_labels",
            "managed_resource_names",
            "teardown_check_commands",
        )

        for name in required_variables:
            self.assertIn(f'variable "{name}"', variables)
        for name in required_outputs:
            self.assertIn(f'output "{name}"', outputs)
        self.assertIn('value       = "aws"', outputs)

    def test_provider_is_static_validation_friendly(self):
        providers = self.read("providers.tf")

        self.assertIn("static-validation-access-key", providers)
        self.assertIn("skip_credentials_validation = var.static_validation_mode", providers)
        self.assertIn("skip_metadata_api_check     = var.static_validation_mode", providers)
        self.assertIn("skip_requesting_account_id  = var.static_validation_mode", providers)

    def test_scaffold_uses_run_scoped_aws_resources(self):
        main = self.read("main.tf")

        for resource_type in (
            "aws_vpc",
            "aws_subnet",
            "aws_eks_cluster",
            "aws_eks_node_group",
        ):
            self.assertIn(f'resource "{resource_type}"', main)
        self.assertIn("RunId           = local.run_id", main)
        self.assertIn('capacity_type   = var.enable_spot_nodes ? "SPOT" : "ON_DEMAND"', main)
        self.assertNotIn('data "aws_availability_zones"', main)

    def test_aws_pricing_fixture_entries_exist(self):
        prices = json.loads(PRICING.read_text(encoding="utf-8"))["prices"]
        keys = {
            (entry["cloud_provider"], entry["region"], entry["machine_type"], entry["pricing_model"])
            for entry in prices
        }

        self.assertIn(("aws", "us-east-1", "m7i.xlarge", "spot"), keys)
        self.assertIn(("aws", "us-east-1", "m7i.xlarge", "on_demand"), keys)
        self.assertIn(("aws", "us-east-1", "c7g.xlarge", "spot"), keys)
        self.assertIn(("aws", "us-east-1", "c7g.xlarge", "on_demand"), keys)

    def test_aws_workflow_promotes_live_benchmark_path(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("Benchmark AWS", workflow)
        self.assertIn("infra/terraform/aws-eks", workflow)
        self.assertIn("aws-actions/configure-aws-credentials", workflow)
        self.assertIn("role-to-assume: ${{ secrets.AWS_ROLE_TO_ASSUME }}", workflow)
        self.assertIn("id-token: write", workflow)
        self.assertIn("-var=\"static_validation_mode=false\"", workflow)
        self.assertIn("terraform apply -auto-approve", workflow)
        self.assertIn("aws eks update-kubeconfig", self.read("outputs.tf"))
        self.assertIn("helm upgrade --install \"$WORKLOAD_RELEASE\"", workflow)
        self.assertIn("helm upgrade --install \"$MONITORING_RELEASE\"", workflow)
        self.assertIn("--cloud-provider aws", workflow)
        self.assertIn("--min-coverage-ratio 0.95", workflow)
        self.assertIn("load_benchmark_summary_to_bigquery.py", workflow)
        self.assertIn("run_acceptance_demo.py", workflow)
        self.assertIn("terraform destroy -auto-approve", workflow)
        self.assertIn("actions/upload-artifact", workflow)
        self.assertIn("teardown-status.env", workflow)
        self.assertNotIn("does not authenticate to AWS", workflow)


if __name__ == "__main__":
    unittest.main()
