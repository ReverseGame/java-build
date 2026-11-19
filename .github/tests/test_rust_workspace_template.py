"""使用本地命令替身验证三条部署路径，禁止访问真实集群。"""

import base64
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
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
    deployment="${3#deployment/}"
    if [ "$SCENARIO" = get_error ] || [ "$deployment" = "$GET_ERROR_DEPLOYMENT" ]; then exit 7; fi
    if [ "$SCENARIO" = existing ] || [[ " $EXISTING_DEPLOYMENTS " == *" $deployment "* ]]; then
      printf 'deployment.apps/%s' "$deployment"
    fi
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
        self.assertEqual(os.name, "posix", "Run the Bash CLI mocks under Linux or WSL")
        step = next(s for s in WORKFLOW["jobs"][job]["steps"]
                    if s.get("name") == "Apply missing Deployment and other resources")
        self.assertEqual(step["if"], "inputs.applyOnlyWhenMissing")
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            (temp / "python").symlink_to(sys.executable)
            for name, script in (("kubectl", KUBECTL), ("aws", AWS)):
                executable = temp / name
                executable.write_text(script, encoding="utf-8", newline="\n")
                executable.chmod(0o755)
            script_path = temp / "create.sh"
            script_path.write_text(step["run"], encoding="utf-8", newline="\n")
            manifest_json = "\n".join(json.dumps(item, indent=2) for item in manifest) if isinstance(manifest, list) else json.dumps(manifest, indent=2)
            (temp / "manifest.json").write_text(manifest_json, encoding="utf-8")
            env = dict(os.environ, PATH=f"{temp}{os.pathsep}{os.environ['PATH']}",
                       NAMESPACE="test-beta",
                       MANIFEST="./deploy/k8s-beta.yaml", CLUSTER_NAME="test-cluster",
                       KUBE_CONFIG_DATA=base64.b64encode(b"test-config").decode(),
                       SCENARIO=scenario, FILTER_ERROR="false", APPLY_ERROR="false",
                       EXISTING_DEPLOYMENTS="", GET_ERROR_DEPLOYMENT="",
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
            ("get_error", mixed, {}, 1),
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
                    self.assertEqual(calls[0], "--namespace=test-beta create --dry-run=client -f ./deploy/k8s-beta.yaml -o json")
                    if "FILTER_ERROR" in overrides or "JSON_ERROR" in overrides:
                        self.assertEqual(len(calls), 1)
                        self.assertIsNone(applied)
                    elif scenario == "get_error":
                        self.assertEqual(len(calls), 2)
                        self.assertIsNone(applied)
                    else:
                        items = manifest if isinstance(manifest, list) else manifest.get("items", [manifest])
                        expected = [item for item in items
                                    if scenario != "existing" or item["kind"] != "Deployment"]
                        if expected:
                            self.assertEqual(applied["items"], expected)
                            self.assertEqual(calls[-1], "--namespace=test-beta apply -f -")
                        else:
                            self.assertIsNone(applied)
                            self.assertFalse(any(" apply " in call for call in calls))

    def test_eks_config_failure(self):
        result, calls, _ = self.run_create("deploy_eks", "missing", {}, AWS_ERROR="true")
        self.assertEqual(result.returncode, 10)
        self.assertEqual(calls, [])

    def test_multiple_deployments(self):
        first = {"apiVersion": "apps/v1", "kind": "Deployment",
                 "metadata": {"name": "test-service"}}
        second = {"apiVersion": "apps/v1", "kind": "Deployment",
                  "metadata": {"name": "second-service"}}
        config = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "config"}}
        service = {"apiVersion": "v1", "kind": "Service", "metadata": {"name": "service"}}
        stream = [config, first, service, second]
        manifests = (stream, {"apiVersion": "v1", "kind": "List", "items": stream})
        cases = (
            ("second-service", "", [config, first, service]),
            ("test-service", "", [config, service, second]),
            ("test-service second-service", "", [config, service]),
            ("", "", stream),
            ("", "second-service", None),
        )
        for job in JOBS:
            for manifest in manifests:
                for existing, query_error, expected in cases:
                    with self.subTest(job=job, stream=isinstance(manifest, list),
                                      existing=existing, query_error=query_error):
                        result, calls, applied = self.run_create(
                            job, "mixed", manifest, EXISTING_DEPLOYMENTS=existing,
                            GET_ERROR_DEPLOYMENT=query_error)
                        queries = [call for call in calls if " get deployment/" in call]
                        self.assertEqual(queries, [
                            "--namespace=test-beta get deployment/test-service --ignore-not-found -o name",
                            "--namespace=test-beta get deployment/second-service --ignore-not-found -o name",
                        ])
                        if query_error:
                            self.assertNotEqual(result.returncode, 0)
                            self.assertIsNone(applied)
                            self.assertFalse(any(" apply " in call for call in calls))
                        else:
                            self.assertEqual(result.returncode, 0, result.stderr)
                            self.assertEqual(applied["items"], expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
