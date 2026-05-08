#!/usr/bin/env python3
"""Calibrate Online Boutique load settings toward a target CPU utilization band."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TrialInput:
    avg_cpu_utilization_pct: float
    request_failure_ratio: float = 0.0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find a reusable SiliconBoutique load profile."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-min-cpu-pct", type=float, default=80.0)
    parser.add_argument("--target-max-cpu-pct", type=float, default=90.0)
    parser.add_argument("--initial-concurrent-users", type=int, default=10)
    parser.add_argument("--initial-users-per-second", type=float, default=1.0)
    parser.add_argument("--max-trials", type=int, default=5)
    parser.add_argument("--trial-duration", default="5m")
    parser.add_argument("--cooldown-seconds", type=float, default=30.0)
    parser.add_argument("--max-failure-ratio", type=float, default=0.05)
    parser.add_argument("--fixture-trials", type=Path)
    parser.add_argument("--artifacts-dir", type=Path, default=Path("artifacts/calibration"))
    parser.add_argument("--run-id-prefix", default="calibration")
    parser.add_argument("--execute-local", action="store_true")
    parser.add_argument("--execute-gcp", action="store_true")
    parser.add_argument("--workflow-file", default=".github/workflows/benchmark.yml")
    parser.add_argument("--project-id", default="")
    parser.add_argument("--region", default="us-central1")
    parser.add_argument("--zone", default="us-central1-a")
    parser.add_argument("--machine-type", default="e2-standard-4")
    parser.add_argument("--node-count", default="1")
    parser.add_argument("--processor-family", default="e2")
    parser.add_argument("--architecture", choices=("x86_64", "arm64"), default="x86_64")
    parser.add_argument("--pricing-model", choices=("spot", "on_demand"), default="spot")
    parser.add_argument("--bigquery-dataset", default="silicon_boutique")
    parser.add_argument("--bigquery-table", default="benchmark_summaries")
    parser.add_argument("--bigquery-location", default="US")
    args = parser.parse_args(argv)
    if args.target_min_cpu_pct <= 0 or args.target_max_cpu_pct <= args.target_min_cpu_pct:
        parser.error("target CPU range must be positive and ordered")
    if args.initial_concurrent_users < 1:
        parser.error("--initial-concurrent-users must be at least 1")
    if args.initial_users_per_second <= 0:
        parser.error("--initial-users-per-second must be positive")
    if args.max_trials < 1:
        parser.error("--max-trials must be at least 1")
    if not 0 <= args.max_failure_ratio <= 1:
        parser.error("--max-failure-ratio must be between 0 and 1")
    modes = [bool(args.fixture_trials), bool(args.execute_local), bool(args.execute_gcp)]
    if sum(1 for enabled in modes if enabled) != 1:
        parser.error("provide exactly one of --fixture-trials, --execute-local, or --execute-gcp")
    if args.execute_gcp and not args.project_id:
        parser.error("--project-id is required with --execute-gcp")
    return args


def main() -> int:
    args = parse_args()
    if args.fixture_trials:
        observations = load_fixture_trials(args.fixture_trials)
        report = calibrate_from_observations(
            observations=observations,
            initial_concurrent_users=args.initial_concurrent_users,
            initial_users_per_second=args.initial_users_per_second,
            target_min_cpu_pct=args.target_min_cpu_pct,
            target_max_cpu_pct=args.target_max_cpu_pct,
            max_trials=args.max_trials,
            max_failure_ratio=args.max_failure_ratio,
            metadata=calibration_metadata(args, "fixture"),
        )
    elif args.execute_local:
        report = calibrate_with_local_runs(args)
    else:
        report = calibrate_with_gcp_workflows(args)
    write_json(args.output, report)
    return 0 if report["status"] == "selected" else 2


def calibrate_from_observations(
    *,
    observations: list[TrialInput],
    initial_concurrent_users: int,
    initial_users_per_second: float,
    target_min_cpu_pct: float,
    target_max_cpu_pct: float,
    max_trials: int,
    max_failure_ratio: float,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    concurrent_users = initial_concurrent_users
    users_per_second = initial_users_per_second
    trials: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None

    for index, observation in enumerate(observations[:max_trials], 1):
        trial = build_trial(
            index=index,
            concurrent_users=concurrent_users,
            users_per_second=users_per_second,
            observation=observation,
            target_min_cpu_pct=target_min_cpu_pct,
            target_max_cpu_pct=target_max_cpu_pct,
            max_failure_ratio=max_failure_ratio,
        )
        trials.append(trial)
        if trial["decision"] == "accept":
            return calibration_report("selected", trials, trial, metadata=metadata)
        if trial["decision"] != "reject_failures":
            best = closer_to_target(best, trial, target_min_cpu_pct, target_max_cpu_pct)
        concurrent_users, users_per_second = next_profile(
            concurrent_users=concurrent_users,
            users_per_second=users_per_second,
            decision=trial["decision"],
        )

    return calibration_report("not_selected", trials, best, metadata=metadata)


def calibrate_with_local_runs(args: argparse.Namespace) -> dict[str, Any]:
    observations: list[TrialInput] = []
    concurrent_users = args.initial_concurrent_users
    users_per_second = args.initial_users_per_second
    trials: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None

    for index in range(1, args.max_trials + 1):
        trial_dir = args.artifacts_dir / f"trial-{index}"
        run_id = f"{args.run_id_prefix}-{index}"
        command = [
            sys.executable,
            "automation/scripts/run_local_benchmark.py",
            "--run-id",
            run_id,
            "--artifacts-dir",
            str(trial_dir),
            "--concurrent-users",
            str(concurrent_users),
            "--users-per-second",
            str(users_per_second),
            "--test-duration",
            args.trial_duration,
            "--min-duration-seconds",
            "1",
        ]
        result = subprocess.run(command, text=True)
        if result.returncode != 0:
            break
        summary = json.loads((trial_dir / "benchmark-summary.json").read_text(encoding="utf-8"))
        failure_ratio = failure_ratio_from_summary(summary)
        observation = TrialInput(
            avg_cpu_utilization_pct=float(summary.get("avg_cpu_utilization_pct") or 0),
            request_failure_ratio=failure_ratio,
        )
        observations.append(observation)
        trial = build_trial(
            index=index,
            source_run_id=run_id,
            concurrent_users=concurrent_users,
            users_per_second=users_per_second,
            observation=observation,
            target_min_cpu_pct=args.target_min_cpu_pct,
            target_max_cpu_pct=args.target_max_cpu_pct,
            max_failure_ratio=args.max_failure_ratio,
        )
        trials.append(trial)
        if trial["decision"] == "accept":
            return calibration_report("selected", trials, trial, metadata=calibration_metadata(args, "local"))
        if trial["decision"] != "reject_failures":
            best = closer_to_target(best, trial, args.target_min_cpu_pct, args.target_max_cpu_pct)
        concurrent_users, users_per_second = next_profile(
            concurrent_users=concurrent_users,
            users_per_second=users_per_second,
            decision=trial["decision"],
        )
        time.sleep(args.cooldown_seconds)

    return calibration_report("not_selected", trials, best, metadata=calibration_metadata(args, "local"))


def calibrate_with_gcp_workflows(args: argparse.Namespace) -> dict[str, Any]:
    concurrent_users = args.initial_concurrent_users
    users_per_second = args.initial_users_per_second
    trials: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None

    for index in range(1, args.max_trials + 1):
        run_id = f"{args.run_id_prefix}-{index}"
        trial_dir = args.artifacts_dir / f"trial-{index}"
        command = gcp_workflow_command(
            args=args,
            run_id=run_id,
            concurrent_users=concurrent_users,
            users_per_second=users_per_second,
        )
        result = subprocess.run(command, text=True)
        if result.returncode != 0:
            break
        summary_path = trial_dir / "benchmark-summary.json"
        if not summary_path.exists():
            trials.append(
                {
                    "trial": index,
                    "source_run_id": run_id,
                    "load_concurrent_users": concurrent_users,
                    "load_users_per_second": round(users_per_second, 6),
                    "decision": "await_artifact",
                    "summary_path": str(summary_path),
                }
            )
            break
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        observation = TrialInput(
            avg_cpu_utilization_pct=float(summary.get("avg_cpu_utilization_pct") or 0),
            request_failure_ratio=failure_ratio_from_summary(summary),
        )
        trial = build_trial(
            index=index,
            source_run_id=run_id,
            concurrent_users=concurrent_users,
            users_per_second=users_per_second,
            observation=observation,
            target_min_cpu_pct=args.target_min_cpu_pct,
            target_max_cpu_pct=args.target_max_cpu_pct,
            max_failure_ratio=args.max_failure_ratio,
        )
        trials.append(trial)
        if trial["decision"] == "accept":
            return calibration_report("selected", trials, trial, metadata=calibration_metadata(args, "gcp"))
        if trial["decision"] != "reject_failures":
            best = closer_to_target(best, trial, args.target_min_cpu_pct, args.target_max_cpu_pct)
        concurrent_users, users_per_second = next_profile(
            concurrent_users=concurrent_users,
            users_per_second=users_per_second,
            decision=trial["decision"],
        )
        time.sleep(args.cooldown_seconds)

    return calibration_report("not_selected", trials, best, metadata=calibration_metadata(args, "gcp"))


def gcp_workflow_command(
    *, args: argparse.Namespace, run_id: str, concurrent_users: int, users_per_second: float
) -> list[str]:
    return [
        "gh",
        "workflow",
        "run",
        args.workflow_file,
        "-f",
        f"project_id={args.project_id}",
        "-f",
        f"region={args.region}",
        "-f",
        f"zone={args.zone}",
        "-f",
        f"machine_type={args.machine_type}",
        "-f",
        f"node_count={args.node_count}",
        "-f",
        f"processor_family={args.processor_family}",
        "-f",
        f"architecture={args.architecture}",
        "-f",
        f"concurrent_users={concurrent_users}",
        "-f",
        f"users_per_second={users_per_second}",
        "-f",
        "load_profile_source=calibration",
        "-f",
        f"pricing_model={args.pricing_model}",
        "-f",
        f"test_duration={args.trial_duration}",
        "-f",
        f"bigquery_dataset={args.bigquery_dataset}",
        "-f",
        f"bigquery_table={args.bigquery_table}",
        "-f",
        f"bigquery_location={args.bigquery_location}",
        "-f",
        "acceptance_demo=false",
    ]


def calibration_metadata(args: argparse.Namespace, mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "machine_type": args.machine_type,
        "processor_family": args.processor_family,
        "architecture": args.architecture,
        "target_min_cpu_pct": args.target_min_cpu_pct,
        "target_max_cpu_pct": args.target_max_cpu_pct,
    }


def build_trial(
    *,
    index: int,
    source_run_id: str | None = None,
    concurrent_users: int,
    users_per_second: float,
    observation: TrialInput,
    target_min_cpu_pct: float,
    target_max_cpu_pct: float,
    max_failure_ratio: float,
) -> dict[str, Any]:
    if observation.request_failure_ratio > max_failure_ratio:
        decision = "reject_failures"
    elif target_min_cpu_pct <= observation.avg_cpu_utilization_pct <= target_max_cpu_pct:
        decision = "accept"
    elif observation.avg_cpu_utilization_pct < target_min_cpu_pct:
        decision = "increase_load"
    else:
        decision = "decrease_load"
    return {
        "trial": index,
        "source_run_id": source_run_id,
        "load_concurrent_users": concurrent_users,
        "load_users_per_second": round(users_per_second, 6),
        "avg_cpu_utilization_pct": observation.avg_cpu_utilization_pct,
        "request_failure_ratio": observation.request_failure_ratio,
        "decision": decision,
    }


def next_profile(
    *, concurrent_users: int, users_per_second: float, decision: str
) -> tuple[int, float]:
    if decision == "increase_load":
        return max(1, int(round(concurrent_users * 1.5))), round(users_per_second * 1.5, 6)
    if decision in {"decrease_load", "reject_failures"}:
        return max(1, int(round(concurrent_users * 0.75))), max(0.1, round(users_per_second * 0.75, 6))
    return concurrent_users, users_per_second


def calibration_report(
    status: str,
    trials: list[dict[str, Any]],
    selected: dict[str, Any] | None,
    *,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_profile = None
    if selected:
        selected_profile = {
            "load_concurrent_users": selected["load_concurrent_users"],
            "load_users_per_second": selected["load_users_per_second"],
            "load_profile_source": "calibration",
            "avg_cpu_utilization_pct": selected["avg_cpu_utilization_pct"],
            "request_failure_ratio": selected.get("request_failure_ratio"),
            "source_run_id": selected.get("source_run_id"),
        }
    return {
        "status": status,
        "metadata": metadata or {},
        "trials": trials,
        "selected_profile": selected_profile,
    }


def closer_to_target(
    current: dict[str, Any] | None,
    candidate: dict[str, Any],
    target_min_cpu_pct: float,
    target_max_cpu_pct: float,
) -> dict[str, Any]:
    if current is None:
        return candidate
    midpoint = (target_min_cpu_pct + target_max_cpu_pct) / 2
    current_distance = abs(current["avg_cpu_utilization_pct"] - midpoint)
    candidate_distance = abs(candidate["avg_cpu_utilization_pct"] - midpoint)
    return candidate if candidate_distance < current_distance else current


def load_fixture_trials(path: Path) -> list[TrialInput]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit("--fixture-trials must contain a JSON array")
    return [
        TrialInput(
            avg_cpu_utilization_pct=float(item["avg_cpu_utilization_pct"]),
            request_failure_ratio=float(item.get("request_failure_ratio", 0.0)),
        )
        for item in payload
    ]


def failure_ratio_from_summary(summary: dict[str, Any]) -> float:
    total = summary.get("request_count_total") or 0
    failures = summary.get("request_failure_count") or 0
    return float(failures) / float(total) if total else 1.0


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
