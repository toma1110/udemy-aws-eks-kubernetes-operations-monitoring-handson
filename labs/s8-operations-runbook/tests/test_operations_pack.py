from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_operations_pack", PACKAGE / "validate_operations_pack.py"
)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)
STATUS_SPEC = importlib.util.spec_from_file_location(
    "validate_common_status_redacted",
    PACKAGE / "scripts" / "validate_common_status_redacted.py",
)
assert STATUS_SPEC and STATUS_SPEC.loader
status_validator = importlib.util.module_from_spec(STATUS_SPEC)
STATUS_SPEC.loader.exec_module(status_validator)


class OperationsPackTests(unittest.TestCase):
    def test_completed_runbook_passes(self):
        validator.validate_runbook(PACKAGE / "fixtures" / "completed-runbook.md")

    def test_template_remains_unfilled_and_completed_fixture_has_no_sensitive_id(self):
        template = (PACKAGE / "templates" / "first-response-runbook.md").read_text(
            encoding="utf-8"
        )
        self.assertRegex(template, validator.PLACEHOLDER)
        completed = (PACKAGE / "fixtures" / "completed-runbook.md").read_text(
            encoding="utf-8"
        )
        self.assertNotRegex(completed, validator.ACCOUNT_ID)
        self.assertNotRegex(completed, validator.ARN)

    def test_missing_runbook_section_fails(self):
        source = (PACKAGE / "fixtures" / "completed-runbook.md").read_text(
            encoding="utf-8"
        )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "runbook.md"
            path.write_text(
                source.replace("## 仮説", "## 別の見出し"), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "missing runbook section"):
                validator.validate_runbook(path)

    def test_sample_inventory_passes(self):
        validator.validate_inventory(
            PACKAGE / "fixtures" / "sample-cost-cleanup-inventory.json"
        )

    def test_unknown_owned_delete_fails(self):
        with self.assertRaisesRegex(ValueError, "unsafe deletion"):
            validator.validate_inventory(
                PACKAGE / "fixtures" / "invalid-authorized-delete.json"
            )

    def test_reordered_cleanup_fails(self):
        source = json.loads(
            (PACKAGE / "fixtures" / "sample-cost-cleanup-inventory.json").read_text(
                encoding="utf-8"
            )
        )
        source["cleanup_order"].reverse()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "inventory.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "cleanup order"):
                validator.validate_inventory(path)

    def test_cli_outputs_are_deterministic(self):
        for kind, name, expected in (
            ("runbook", "completed-runbook.md", "PASS: runbook contract is complete"),
            (
                "inventory",
                "sample-cost-cleanup-inventory.json",
                "PASS: cost and cleanup inventory is safe",
            ),
        ):
            result = subprocess.run(
                [
                    sys.executable,
                    str(PACKAGE / "validate_operations_pack.py"),
                    kind,
                    str(PACKAGE / "fixtures" / name),
                ],
                text=True,
                capture_output=True,
                check=False,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), expected)

    def test_readme_is_cloudshell_first_and_read_only(self):
        readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
        for token in (
            'export AWS_REGION="ap-northeast-1"',
            "aws --version",
            "kubectl version --client --output=json",
            'df -h "$HOME"',
            "Regionごとに1 GB",
            "bind-current-identity.sh",
            "validate_common_status_redacted.py",
            "post-guard-verify.sh",
        ):
            self.assertIn(token, readme)
        for command in (
            "aws eks list-clusters",
            "aws eks describe-cluster",
            "aws cloudformation list-stacks",
            "aws logs describe-log-groups",
        ):
            self.assertIn(command, readme)
        for forbidden in (
            "aws eks delete-cluster",
            "aws cloudformation delete-stack",
            "kubectl delete ",
            "kubectl apply ",
            "aws iam create",
            "aws iam attach",
        ):
            self.assertNotIn(forbidden, readme)

    def test_common_status_success_stdout_is_private_and_redacted(self):
        readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
        wrapper = PACKAGE / "scripts" / "validate_common_status_redacted.py"
        wrapper_text = wrapper.read_text(encoding="utf-8")
        self.assertIn(
            'python3 "$S8_DIR/scripts/validate_common_status_redacted.py"', readme
        )
        self.assertNotIn('"$COMMON_EKS_DIR/scripts/status.sh"\n', readme)
        self.assertIn('status_script = common_dir / "scripts" / "status.sh"', wrapper_text)
        self.assertIn("stdout=output", wrapper_text)
        self.assertNotIn("capture_output=True", wrapper_text)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            common_scripts = root / "common" / "scripts"
            private = root / "private"
            common_scripts.mkdir(parents=True)
            private.mkdir(mode=0o700)
            dependency = common_scripts / "status.sh"
            dependency.write_text("# dependency fixture\n", encoding="utf-8")

            def fake_status(command, **kwargs):
                self.assertEqual(command, [str(dependency)])
                self.assertIn("stdout", kwargs)
                self.assertNotIn("stderr", kwargs)
                kwargs["stdout"].write(b"RAW-SENSITIVE-STATUS-OUTPUT\n")
                return SimpleNamespace(returncode=0)

            visible_stdout = io.StringIO()
            visible_stderr = io.StringIO()
            with (
                mock.patch.object(
                    status_validator.subprocess, "run", side_effect=fake_status
                ),
                redirect_stdout(visible_stdout),
                redirect_stderr(visible_stderr),
            ):
                result = status_validator.validate_common_status(
                    root / "common", private
                )
            self.assertEqual(result, 0, visible_stderr.getvalue())
            self.assertEqual(
                visible_stdout.getvalue().strip(),
                "Common EKS status validation passed.",
            )
            visible = visible_stdout.getvalue() + visible_stderr.getvalue()
            self.assertNotIn("RAW-SENSITIVE-STATUS-OUTPUT", visible)
            self.assertEqual(list(private.iterdir()), [])

    def test_common_status_failure_retains_stderr_but_not_partial_stdout(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            common_scripts = root / "common" / "scripts"
            private = root / "private"
            common_scripts.mkdir(parents=True)
            private.mkdir(mode=0o700)
            dependency = common_scripts / "status.sh"
            dependency.write_text("# dependency fixture\n", encoding="utf-8")

            def fake_failure(command, **kwargs):
                self.assertEqual(command, [str(dependency)])
                self.assertNotIn("stderr", kwargs)
                kwargs["stdout"].write(b"RAW-SENSITIVE-STATUS-OUTPUT\n")
                return SimpleNamespace(returncode=7)

            visible_stdout = io.StringIO()
            visible_stderr = io.StringIO()
            with (
                mock.patch.object(
                    status_validator.subprocess, "run", side_effect=fake_failure
                ),
                redirect_stdout(visible_stdout),
                redirect_stderr(visible_stderr),
            ):
                result = status_validator.validate_common_status(
                    root / "common", private
                )
            self.assertNotEqual(result, 0)
            self.assertEqual(visible_stdout.getvalue(), "")
            self.assertIn("use the diagnostic above", visible_stderr.getvalue())
            self.assertNotIn("RAW-SENSITIVE-STATUS-OUTPUT", visible_stderr.getvalue())
            self.assertEqual(list(private.iterdir()), [])

    def test_learner_package_has_no_nonlearner_wording(self):
        readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
        expected = (PACKAGE / "expected-results.json").read_text(encoding="utf-8")
        for internal in (
            "Work" + "er",
            "Review" + "er",
            "run " + "state",
            "artifact " + "hash",
            "technical " + "review",
        ):
            self.assertNotIn(internal, readme)
            self.assertNotIn(internal, expected)


if __name__ == "__main__":
    unittest.main()
