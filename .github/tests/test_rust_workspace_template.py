"""使用本地命令替身验证三条部署路径，禁止访问真实集群。"""

import base64
import json
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = yaml.safe_load(
    (ROOT / ".github/workflows/rust-workspace-template.yml").read_text(encoding="utf-8")
)
JOBS = ("deploy_local", "deploy_product", "deploy_eks")
KUBECTL = """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$CALLS"
case "$*" in
  *' get deployment/'*)
    if [ "$SCENARIO" = get_error ]; then exit 7; fi
    if [ "$SCENARIO" = existing ]; then printf 'deployment.apps/test-service'; fi
    ;;
  *' create --dry-run=client '*)
    if [ "$FILTER_ERROR" = true ]; then exit 8; fi
    if [ "$JSON_ERROR" = true ]; then printf invalid; else cat "$MANIFEST_JSON"; fi
    ;;
  *' apply -f -')
    cat > "$APPLIED_JSON"
    if [ "$APPLY_ERROR" = true ]; then exit 9; fi
    ;;
  *' apply -f '*)
    if [ "$APPLY_ERROR" = true ]; then exit 9; fi
    ;;
  *) exit 99 ;;
esac
"""
AWS = """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$AWS_CALLS"
if [ "$AWS_ERROR" = true ]; then exit 10; fi
"""


class DeploymentTemplateTest(unittest.TestCase):
    def test_opt_in_contract(self):
        # PyYAML 的 YAML 1.1 会将 on 解析为 True。
        inputs = WORKFLOW[True]["workflow_call"]["inputs"]
        self.assertEqual(inputs["applyOnlyWhenMissing"]["type"], "boolean")
        self.assertIs(inputs["applyOnlyWhenMissing"]["default"], False)
        for job in JOBS:
            with self.subTest(job=job):
                steps = WORKFLOW["jobs"][job]["steps"]
                legacy = next(s for s in steps if s.get("name") in (
                    "create", "deploy to fellas cluster"
                ))
                self.assertEqual(legacy["if"], "${{ !inputs.applyOnlyWhenMissing }}")
                image = next(s for s in steps if s.get("name") == "apply")
                self.assertNotIn("if", image)
                self.assertIn(" set image deployment/", str(image["with"]))
                rollout = next(s for s in steps if s.get("name") == "Wait for Deployment rollout")
                self.assertEqual(rollout["if"], "inputs.applyOnlyWhenMissing")
                self.assertGreater(steps.index(rollout), steps.index(image))
                self.assertIn("--timeout=5m", str(rollout["with"]))

    def run_create(self, job, scenario, manifest, **overrides):
        step = next(s for s in WORKFLOW["jobs"][job]["steps"]
                    if s.get("name") == "Apply missing Deployment and other resources")
        self.assertEqual(step["if"], "inputs.applyOnlyWhenMissing")
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            for name, script in (("kubectl", KUBECTL), ("aws", AWS)):
                executable = temp / name
                executable.write_text(script, encoding="utf-8", newline="\n")
                executable.chmod(0o755)
            script_path = temp / "create.sh"
            script_path.write_text(step["run"], encoding="utf-8", newline="\n")
            manifest_json = "\n".join(json.dumps(item) for item in manifest) if isinstance(manifest, list) else json.dumps(manifest)
            (temp / "manifest.json").write_text(manifest_json, encoding="utf-8")
            env = dict(os.environ, PATH=f"{temp}{os.pathsep}{os.environ['PATH']}",
                       NAMESPACE="test-beta", PROJECT_NAME="test-service",
                       MANIFEST="./deploy/k8s-beta.yaml", CLUSTER_NAME="test-cluster",
                       KUBE_CONFIG_DATA=base64.b64encode(b"test-config").decode(),
                       SCENARIO=scenario, FILTER_ERROR="false", APPLY_ERROR="false",
                       AWS_ERROR="false", JSON_ERROR="false", CALLS=(temp / "calls").as_posix(),
                       AWS_CALLS=(temp / "aws-calls").as_posix(),
                       MANIFEST_JSON=(temp / "manifest.json").as_posix(),
                       APPLIED_JSON=(temp / "applied.json").as_posix())
            env.update(overrides)
            syntax = subprocess.run([shutil.which("bash"), "-n", script_path.as_posix()],
                                    capture_output=True, text=True, env=env)
            self.assertEqual(syntax.returncode, 0, syntax.stderr)
            result = subprocess.run([shutil.which("bash"), "-euo", "pipefail", script_path.as_posix()],
                                    capture_output=True, text=True, env=env, timeout=15)
            calls = (temp / "calls").read_text() if (temp / "calls").exists() else ""
            applied = json.loads((temp / "applied.json").read_text()) if (temp / "applied.json").exists() else None
            if job == "deploy_eks":
                self.assertIn("eks update-kubeconfig --name test-cluster --kubeconfig",
                              (temp / "aws-calls").read_text())
            return result, calls.splitlines(), applied

    def test_create_paths(self):
        deployment = {"apiVersion": "apps/v1", "kind": "Deployment",
                      "metadata": {"name": "test-service"}}
        resources = [{"apiVersion": version, "kind": kind, "metadata": {"name": "test"}}
                     for version, kind in (("v1", "ConfigMap"), ("v1", "Service"),
                                           ("autoscaling/v2", "HorizontalPodAutoscaler"),
                                           ("batch/v1", "Job"))]
        mixed = {"apiVersion": "v1", "kind": "List", "items": [deployment, *resources]}
        stream = [deployment, *resources]
        cases = (
            ("existing", stream, {}, 0),
            ("missing", mixed, {}, 0),
            ("existing", mixed, {}, 0),
            ("existing", deployment, {}, 0),
            ("existing", resources[0], {}, 0),
            ("get_error", mixed, {}, 7),
            ("missing", mixed, {"APPLY_ERROR": "true"}, 9),
            ("existing", mixed, {"FILTER_ERROR": "true"}, 8),
            ("existing", mixed, {"APPLY_ERROR": "true"}, 9),
            ("existing", mixed, {"JSON_ERROR": "true"}, 1),
        )
        for job in JOBS:
            for scenario, manifest, overrides, expected_code in cases:
                with self.subTest(job=job, scenario=scenario, manifest="stream" if isinstance(manifest, list) else manifest["kind"], overrides=overrides):
                    result, calls, applied = self.run_create(job, scenario, manifest, **overrides)
                    self.assertEqual(result.returncode, expected_code, result.stderr)
                    self.assertIn("get deployment/test-service --ignore-not-found -o name", calls[0])
                    if scenario == "get_error":
                        self.assertEqual(len(calls), 1)
                    elif scenario == "missing":
                        self.assertEqual(len(calls), 2)
                        self.assertEqual(calls[1], "--namespace=test-beta apply -f ./deploy/k8s-beta.yaml")
                    elif expected_code in (1, 8):
                        self.assertEqual(len(calls), 2)
                    elif manifest == deployment:
                        self.assertEqual(len(calls), 2)
                        self.assertIsNone(applied)
                    else:
                        expected = resources if manifest in (mixed, stream) else [manifest]
                        self.assertEqual(applied["items"], expected)
                        self.assertEqual(calls[-1], "--namespace=test-beta apply -f -")

    def test_eks_config_failure(self):
        result, calls, _ = self.run_create("deploy_eks", "missing", {}, AWS_ERROR="true")
        self.assertEqual(result.returncode, 10)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
