import hashlib
import copy
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

JQ_IDENTITY_DOUBLE = """#!/usr/bin/env python3
import json
import re
import sys

document = json.load(sys.stdin)
if sys.argv[1:3] == ["-S", "."]:
    json.dump(document, sys.stdout, sort_keys=True, indent=2)
    sys.stdout.write("\\n")
    raise SystemExit(0)
if not sys.argv[1:] or sys.argv[1] != "-e":
    raise SystemExit(2)
valid = (
    set(document) == {"Account", "Arn", "UserId"}
    and isinstance(document["Account"], str)
    and re.fullmatch(r"[0-9]{12}", document["Account"]) is not None
    and isinstance(document["Arn"], str)
    and re.fullmatch(
        r"arn:[^:]+:(?:iam|sts)::([0-9]{12}):.+", document["Arn"]
    ) is not None
    and re.fullmatch(
        r"arn:[^:]+:(?:iam|sts)::([0-9]{12}):.+", document["Arn"]
    ).group(1) == document["Account"]
    and isinstance(document["UserId"], str)
    and len(document["UserId"]) > 0
)
raise SystemExit(0 if valid else 1)
"""


def wsl_path(path):
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    return f"/mnt/{drive}/{resolved.as_posix().split(':', 1)[1].lstrip('/')}"


def run_bash(body):
    common = shlex.quote(wsl_path(ROOT / "scripts" / "common.sh"))
    result = subprocess.run(
        ["bash"],
        input=f"set -euo pipefail\nsource {common}\n{body}\n".encode(),
        capture_output=True,
        check=False,
    )
    result.stdout = result.stdout.decode()
    result.stderr = result.stderr.decode()
    return result


class CfnLoader(yaml.SafeLoader):
    pass


def unknown(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


CfnLoader.add_multi_constructor("!", unknown)


class CommonEksContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / "template.yaml").read_text(encoding="utf-8")
        cls.template = yaml.load(cls.text, Loader=CfnLoader)
        cls.guard_text = (ROOT / "cleanup-guard.yaml").read_text(encoding="utf-8")
        cls.guard_template = yaml.load(cls.guard_text, Loader=CfnLoader)
        cls.rollback_fixture = json.loads(
            (ROOT / "fixtures" / "rollback-complete-stack.json").read_text(
                encoding="utf-8"
            )
        )
        cls.scripts = {
            path.name: path.read_text(encoding="utf-8")
            for path in (ROOT / "scripts").glob("*.sh")
        }
        cls.joined = "\n".join(cls.scripts.values())

    def test_cloudshell_bash_is_the_only_learner_script_contract(self):
        self.assertEqual(
            {
                "common.sh",
                "create.sh",
                "delete.sh",
                "bind-current-identity.sh",
                "post-guard-verify.sh",
                "preflight.sh",
                "recover-cidr.sh",
                "status.sh",
                "verify-cleanup.sh",
            },
            set(self.scripts),
        )
        self.assertFalse(list((ROOT / "scripts").glob("*.ps1")))
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for token in (
            "AWS CloudShell",
            "Bash",
            "local PowerShellは不要",
            "aws --version",
            "kubectl version --client --output=json",
            "ap-northeast-1",
            "$HOME",
            "1 GB",
        ):
            self.assertIn(token, readme)
        self.assertNotIn("受講者向けの既定実行環境", readme)

    def test_current_sts_identity_is_validated_and_written_only_to_private_path(self):
        preflight = self.scripts["preflight.sh"]
        common = self.scripts["common.sh"]
        self.assertIn("record_current_sts_identity", preflight)
        for token in (
            "sts get-caller-identity",
            "CURRENT_STS_IDENTITY_FILE",
            "outside every Git worktree",
            "umask 077",
            'test("^[0-9]{12}$")',
        ):
            self.assertIn(token, common)
        self.assertNotIn('printf \'%s\\n\' "$identity"', common)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            jq_path = temp_root / "jq"
            jq_path.write_text(JQ_IDENTITY_DOUBLE, encoding="utf-8", newline="\n")
            jq_path.chmod(0o755)
            identity_path = temp_root / "current-sts-identity.json"
            identity_argument = shlex.quote(wsl_path(identity_path))
            path_argument = shlex.quote(wsl_path(temp_root))
            first_account = "123456" + "789012"
            second_account = "210987" + "654321"
            valid = json.dumps(
                {
                    "Account": first_account,
                    "Arn": (
                        f"arn:aws:sts::{first_account}:"
                        "assumed-role/example/session"
                    ),
                    "UserId": "example:session",
                },
                separators=(",", ":"),
            )
            accepted = run_bash(
                f"export PATH={path_argument}:$PATH; "
                f"aws() {{ printf '%s\\n' {shlex.quote(valid)}; }}; "
                f"export CURRENT_STS_IDENTITY_FILE={identity_argument}; "
                "record_current_sts_identity"
            )
            self.assertEqual(0, accepted.returncode, accepted.stderr)
            self.assertEqual("", accepted.stdout)
            stored = json.loads(identity_path.read_text(encoding="utf-8"))
            self.assertEqual(set(stored), {"Account", "Arn", "UserId"})

            changed_current = json.dumps(
                {
                    "Account": second_account,
                    "Arn": (
                        f"arn:aws:sts::{second_account}:"
                        "assumed-role/example/session"
                    ),
                    "UserId": "other:session",
                },
                separators=(",", ":"),
            )
            changed_rejected = run_bash(
                f"export PATH={path_argument}:$PATH; "
                f"aws() {{ printf '%s\\n' {shlex.quote(changed_current)}; }}; "
                f"export CURRENT_STS_IDENTITY_FILE={identity_argument}; "
                "record_current_sts_identity"
            )
            self.assertNotEqual(0, changed_rejected.returncode)
            self.assertEqual(stored, json.loads(identity_path.read_text(encoding="utf-8")))

            mismatched = json.dumps(
                {
                    "Account": first_account,
                    "Arn": (
                        f"arn:aws:sts::{second_account}:"
                        "assumed-role/example/session"
                    ),
                    "UserId": "example:session",
                },
                separators=(",", ":"),
            )
            rejected = run_bash(
                f"export PATH={path_argument}:$PATH; "
                f"aws() {{ printf '%s\\n' {shlex.quote(mismatched)}; }}; "
                f"export CURRENT_STS_IDENTITY_FILE={identity_argument}; "
                "record_current_sts_identity"
            )
            self.assertNotEqual(0, rejected.returncode)

    def test_single_identity_lifecycle_and_post_guard_repeat_zero(self):
        common_readme = (ROOT / "README.md").read_text(encoding="utf-8")
        s4_readme = (
            ROOT.parent / "s4-cloudwatch-logs-insights" / "README.md"
        ).read_text(encoding="utf-8")
        self.assertIn('source "$COMMON_EKS_DIR/scripts/bind-current-identity.sh"', common_readme)
        self.assertIn(
            "$HOME/eks-monitoring-private/c010-s4/current-run/current-sts-identity.json",
            common_readme,
        )
        self.assertNotIn(
            'export PRIVATE_EXECUTION_DIR="$HOME/eks-monitoring-private/s4-',
            s4_readme,
        )
        self.assertNotIn(
            'export CURRENT_STS_IDENTITY_FILE="$PRIVATE_EXECUTION_DIR/',
            s4_readme,
        )
        for token in (
            'source "$COMMON_EKS_DIR/scripts/bind-current-identity.sh"',
            "Section 4用の2個目",
            'scripts/post-guard-verify.sh"',
        ):
            self.assertIn(token, s4_readme)

        bind_script = ROOT / "scripts" / "bind-current-identity.sh"
        bind_text = bind_script.read_text(encoding="utf-8")
        for token in (
            "c010-s4",
            "current-run",
            "Multiple retained current-run identity candidates",
            "retained identity exists at a foreign path",
            "Malformed or foreign retained private artifacts",
            "record_current_sts_identity",
        ):
            self.assertIn(token, bind_text)

        with tempfile.TemporaryDirectory() as bind_temp:
            bind_root = Path(bind_temp)
            jq_path = bind_root / "jq"
            jq_path.write_text(JQ_IDENTITY_DOUBLE, encoding="utf-8", newline="\n")
            jq_path.chmod(0o755)
            home = bind_root / "home"
            home.mkdir()
            path_argument = shlex.quote(wsl_path(bind_root))
            home_argument = shlex.quote(wsl_path(home))
            bind_argument = shlex.quote(wsl_path(bind_script))
            first_account = "123456" + "789012"
            second_account = "210987" + "654321"

            def identity_document(account: str) -> str:
                return json.dumps(
                    {
                        "Account": account,
                        "Arn": (
                            f"arn:aws:sts::{account}:"
                            "assumed-role/example/session"
                        ),
                        "UserId": "example:session",
                    },
                    separators=(",", ":"),
                )

            def bind_at(
                target_home: Path,
                account: str,
                *,
                raw_document: str | None = None,
                prelude: str = "",
                command_path: Path | None = None,
            ) -> subprocess.CompletedProcess[str]:
                document = raw_document or identity_document(account)
                target_home_argument = shlex.quote(wsl_path(target_home))
                command_path_argument = shlex.quote(
                    wsl_path(command_path or bind_root)
                )
                result = subprocess.run(
                    ["bash"],
                    input=(
                        "set -euo pipefail\n"
                        f"export HOME={target_home_argument}\n"
                        f"export PATH={command_path_argument}:$PATH\n"
                        f"aws() {{ printf '%s\\n' {shlex.quote(document)}; }}\n"
                        "export -f aws\n"
                        f"{prelude}\n"
                        f"if source {bind_argument}; then\n"
                        "  bind_status=0\n"
                        "else\n"
                        "  bind_status=$?\n"
                        "fi\n"
                        'if ((bind_status != 0)); then exit "$bind_status"; fi\n'
                        'test "$PRIVATE_EXECUTION_DIR" = '
                        '"$HOME/eks-monitoring-private/c010-s4/current-run"\n'
                        'test "$CURRENT_STS_IDENTITY_FILE" = '
                        '"$PRIVATE_EXECUTION_DIR/current-sts-identity.json"\n'
                    ).encode(),
                    capture_output=True,
                    check=False,
                )
                result.stdout = result.stdout.decode()
                result.stderr = result.stderr.decode()
                return result

            def bind(account: str) -> subprocess.CompletedProcess[str]:
                return bind_at(home, account)

            identity_path = (
                home
                / "eks-monitoring-private"
                / "c010-s4"
                / "current-run"
                / "current-sts-identity.json"
            )
            direct_home = bind_root / "home-direct"
            direct_home.mkdir()
            direct = run_bash(
                f"export HOME={shlex.quote(wsl_path(direct_home))}; "
                f"export PATH={path_argument}:$PATH; "
                f"bash {bind_argument}"
            )
            self.assertNotEqual(0, direct.returncode)
            self.assertFalse((direct_home / "eks-monitoring-private").exists())

            initial = bind(first_account)
            self.assertEqual(0, initial.returncode, initial.stderr)
            initial_bytes = identity_path.read_bytes()
            self.assertEqual(
                [identity_path],
                list((home / "eks-monitoring-private" / "c010-s4").rglob(
                    "current-sts-identity.json"
                )),
            )

            reconnect = bind(first_account)
            self.assertEqual(0, reconnect.returncode, reconnect.stderr)
            self.assertEqual(initial_bytes, identity_path.read_bytes())

            second_find_failure = bind_at(
                home,
                first_account,
                prelude=(
                    "find_call_count=0; "
                    "find() { find_call_count=$((find_call_count + 1)); "
                    "if ((find_call_count == 2)); then return 43; fi; "
                    'command find "$@"; }; export -f find'
                ),
            )
            self.assertEqual(43, second_find_failure.returncode)
            self.assertEqual(initial_bytes, identity_path.read_bytes())
            self.assertFalse(
                list(
                    (home / "eks-monitoring-private").glob(
                        ".c010-s4-discovery.*"
                    )
                )
            )
            second_read_failure = bind_at(
                home,
                first_account,
                prelude=(
                    "mapfile_call_count=0; "
                    "mapfile() { "
                    "mapfile_call_count=$((mapfile_call_count + 1)); "
                    "if ((mapfile_call_count == 2)); then return 46; fi; "
                    'builtin mapfile "$@"; }'
                ),
            )
            self.assertEqual(46, second_read_failure.returncode)
            self.assertEqual(initial_bytes, identity_path.read_bytes())
            self.assertFalse(
                list(
                    (home / "eks-monitoring-private").glob(
                        ".c010-s4-discovery.*"
                    )
                )
            )

            mismatch = bind(second_account)
            self.assertNotEqual(0, mismatch.returncode)
            self.assertEqual(initial_bytes, identity_path.read_bytes())

            foreign_dir = (
                home / "eks-monitoring-private" / "c010-s4" / "foreign-run"
            )
            foreign_dir.mkdir()
            foreign_identity = foreign_dir / "current-sts-identity.json"
            foreign_identity.write_bytes(initial_bytes)
            multiple = bind(first_account)
            self.assertNotEqual(0, multiple.returncode)
            self.assertEqual(initial_bytes, identity_path.read_bytes())
            foreign_identity.unlink()
            foreign_dir.rmdir()

            expected_dir = identity_path.parent
            foreign_dir.mkdir()
            identity_path.replace(foreign_identity)
            foreign_only = bind(first_account)
            self.assertNotEqual(0, foreign_only.returncode)
            self.assertFalse(identity_path.exists())
            foreign_bytes = foreign_identity.read_bytes()
            foreign_find_failure = bind_at(
                home,
                first_account,
                prelude=(
                    "find_call_count=0; "
                    "find() { find_call_count=$((find_call_count + 1)); "
                    "if ((find_call_count == 1)); then return 77; fi; "
                    'command find "$@"; }; export -f find'
                ),
            )
            self.assertNotEqual(0, foreign_find_failure.returncode)
            self.assertEqual(foreign_bytes, foreign_identity.read_bytes())
            self.assertFalse(
                list(
                    (home / "eks-monitoring-private").glob(
                        ".c010-s4-discovery.*"
                    )
                )
            )
            foreign_identity.replace(identity_path)
            foreign_dir.rmdir()

            identity_path.write_text("{malformed\n", encoding="utf-8", newline="\n")
            malformed = bind(first_account)
            self.assertNotEqual(0, malformed.returncode)
            self.assertEqual(b"{malformed\n", identity_path.read_bytes())
            identity_path.write_bytes(initial_bytes)

            unexpected = expected_dir / "unexpected.txt"
            unexpected.write_text("retain\n", encoding="utf-8", newline="\n")
            unexpected_shape = bind(first_account)
            self.assertNotEqual(0, unexpected_shape.returncode)
            self.assertEqual(initial_bytes, identity_path.read_bytes())
            self.assertEqual("retain\n", unexpected.read_text(encoding="utf-8"))
            unexpected.unlink()

            def assert_atomic_failure_has_no_orphan(
                label: str,
                *,
                raw_document: str | None = None,
                prelude: str = "",
                command_path: Path | None = None,
            ) -> Path:
                fault_home = bind_root / f"home-{label}"
                fault_home.mkdir()
                result = bind_at(
                    fault_home,
                    first_account,
                    raw_document=raw_document,
                    prelude=prelude,
                    command_path=command_path,
                )
                self.assertNotEqual(0, result.returncode, label)
                course_root = (
                    fault_home / "eks-monitoring-private" / "c010-s4"
                )
                self.assertFalse((course_root / "current-run").exists(), label)
                self.assertFalse(
                    list(course_root.glob(".current-run.tmp.*"))
                    if course_root.exists()
                    else [],
                    label,
                )
                discovery_parent = fault_home / "eks-monitoring-private"
                self.assertFalse(
                    list(discovery_parent.glob(".c010-s4-discovery.*"))
                    if discovery_parent.exists()
                    else [],
                    label,
                )
                return fault_home

            first_find_home = assert_atomic_failure_has_no_orphan(
                "find-first",
                prelude="find() { return 42; }; export -f find",
            )
            first_find_failure = bind_at(
                bind_root / "home-find-first-status",
                first_account,
                prelude="find() { return 42; }; export -f find",
            )
            self.assertEqual(42, first_find_failure.returncode)
            first_find_retry = bind_at(first_find_home, first_account)
            self.assertEqual(
                0, first_find_retry.returncode, first_find_retry.stderr
            )
            read_home = assert_atomic_failure_has_no_orphan(
                "read",
                prelude="mapfile() { return 45; }",
            )
            first_read_failure = bind_at(
                bind_root / "home-read-first-status",
                first_account,
                prelude="mapfile() { return 45; }",
            )
            self.assertEqual(45, first_read_failure.returncode)
            read_retry = bind_at(read_home, first_account)
            self.assertEqual(0, read_retry.returncode, read_retry.stderr)
            third_find_home = assert_atomic_failure_has_no_orphan(
                "find-third",
                prelude=(
                    "find_call_count=0; "
                    "find() { find_call_count=$((find_call_count + 1)); "
                    "if ((find_call_count == 3)); then return 44; fi; "
                    'command find "$@"; }; export -f find'
                ),
            )
            third_find_status_home = bind_root / "home-find-third-status"
            third_find_status_home.mkdir()
            third_find_failure = bind_at(
                third_find_status_home,
                first_account,
                prelude=(
                    "find_call_count=0; "
                    "find() { find_call_count=$((find_call_count + 1)); "
                    "if ((find_call_count == 3)); then return 44; fi; "
                    'command find "$@"; }; export -f find'
                ),
            )
            self.assertEqual(44, third_find_failure.returncode)
            third_find_retry = bind_at(third_find_home, first_account)
            self.assertEqual(
                0, third_find_retry.returncode, third_find_retry.stderr
            )
            third_read_home = assert_atomic_failure_has_no_orphan(
                "read-third",
                prelude=(
                    "mapfile_call_count=0; "
                    "mapfile() { "
                    "mapfile_call_count=$((mapfile_call_count + 1)); "
                    "if ((mapfile_call_count == 3)); then return 47; fi; "
                    'builtin mapfile "$@"; }'
                ),
            )
            third_read_status_home = bind_root / "home-read-third-status"
            third_read_status_home.mkdir()
            third_read_failure = bind_at(
                third_read_status_home,
                first_account,
                prelude=(
                    "mapfile_call_count=0; "
                    "mapfile() { "
                    "mapfile_call_count=$((mapfile_call_count + 1)); "
                    "if ((mapfile_call_count == 3)); then return 47; fi; "
                    'builtin mapfile "$@"; }'
                ),
            )
            self.assertEqual(47, third_read_failure.returncode)
            third_read_retry = bind_at(third_read_home, first_account)
            self.assertEqual(
                0, third_read_retry.returncode, third_read_retry.stderr
            )

            private_env_home = assert_atomic_failure_has_no_orphan(
                "private-env",
                prelude="export PRIVATE_EXECUTION_DIR=/tmp/foreign-private-binding",
            )
            self.assertFalse(
                (private_env_home / "eks-monitoring-private").exists()
            )
            identity_env_home = assert_atomic_failure_has_no_orphan(
                "identity-env",
                prelude=(
                    "export CURRENT_STS_IDENTITY_FILE="
                    "/tmp/foreign-private-binding/identity.json"
                ),
            )
            self.assertFalse(
                (identity_env_home / "eks-monitoring-private").exists()
            )
            orphan_home = bind_root / "home-orphan"
            orphan_dir = (
                orphan_home
                / "eks-monitoring-private"
                / "c010-s4"
                / "current-run"
            )
            orphan_dir.mkdir(parents=True)
            orphan_file = orphan_dir / "orphan.txt"
            orphan_file.write_text("retain\n", encoding="utf-8", newline="\n")
            orphan_shape = bind_at(orphan_home, first_account)
            self.assertNotEqual(0, orphan_shape.returncode)
            self.assertEqual("retain\n", orphan_file.read_text(encoding="utf-8"))
            self.assertFalse(
                (orphan_dir / "current-sts-identity.json").exists()
            )
            mkdir_home = assert_atomic_failure_has_no_orphan(
                "mkdir",
                prelude="mkdir() { return 75; }; export -f mkdir",
            )
            mkdir_retry = bind_at(mkdir_home, first_account)
            self.assertEqual(0, mkdir_retry.returncode, mkdir_retry.stderr)
            mktemp_home = assert_atomic_failure_has_no_orphan(
                "mktemp",
                prelude="mktemp() { return 73; }; export -f mktemp",
            )
            mktemp_retry = bind_at(mktemp_home, first_account)
            self.assertEqual(0, mktemp_retry.returncode, mktemp_retry.stderr)

            chmod_home = assert_atomic_failure_has_no_orphan(
                "chmod",
                prelude="chmod() { return 74; }; export -f chmod",
            )
            chmod_retry = bind_at(chmod_home, first_account)
            self.assertEqual(0, chmod_retry.returncode, chmod_retry.stderr)

            sts_home = bind_root / "home-sts"
            sts_home.mkdir()
            sts_failure = subprocess.run(
                ["bash"],
                input=(
                    "set -euo pipefail\n"
                    f"export HOME={shlex.quote(wsl_path(sts_home))}\n"
                    f"export PATH={path_argument}:$PATH\n"
                    "aws() { return 1; }\n"
                    "export -f aws\n"
                    f"if source {bind_argument}; then exit 0; "
                    "else exit $?; fi\n"
                ).encode(),
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(0, sts_failure.returncode)
            self.assertFalse((sts_home / "eks-monitoring-private").exists())

            malformed_home = assert_atomic_failure_has_no_orphan(
                "malformed", raw_document="{malformed"
            )
            malformed_retry = bind_at(malformed_home, first_account)
            self.assertEqual(0, malformed_retry.returncode, malformed_retry.stderr)

            write_bin = bind_root / "write-bin"
            write_bin.mkdir()
            write_jq = write_bin / "jq"
            write_jq.write_text(
                (
                    "#!/usr/bin/env bash\n"
                    "if [[ \"$1\" == \"-S\" ]]; then exit 71; fi\n"
                    f"exec {shlex.quote(wsl_path(jq_path))} \"$@\"\n"
                ),
                encoding="utf-8",
                newline="\n",
            )
            write_jq.chmod(0o755)
            write_home = assert_atomic_failure_has_no_orphan(
                "write", command_path=write_bin
            )
            write_retry = bind_at(write_home, first_account)
            self.assertEqual(0, write_retry.returncode, write_retry.stderr)

            finalize_home = assert_atomic_failure_has_no_orphan(
                "finalize",
                prelude=(
                    "mv() { if [[ \"$1\" == \"-T\" ]]; then return 72; fi; "
                    "command mv \"$@\"; }; export -f mv"
                ),
            )
            finalize_retry = bind_at(finalize_home, first_account)
            self.assertEqual(0, finalize_retry.returncode, finalize_retry.stderr)

            collision_home = bind_root / "home-collision"
            collision_home.mkdir()
            collision_expected = (
                collision_home
                / "eks-monitoring-private"
                / "c010-s4"
                / "current-run"
            )
            collision_prelude = (
                "mv() { if [[ \"$1\" == \"-T\" ]]; then "
                f"mkdir -p {shlex.quote(wsl_path(collision_expected))}; "
                f"cp \"$4/current-sts-identity.json\" "
                f"{shlex.quote(wsl_path(collision_expected / 'current-sts-identity.json'))}; "
                "return 0; fi; command mv \"$@\"; }; export -f mv"
            )
            collision = bind_at(
                collision_home,
                first_account,
                prelude=collision_prelude,
            )
            self.assertNotEqual(0, collision.returncode)
            collision_identity = collision_expected / "current-sts-identity.json"
            self.assertTrue(collision_identity.is_file())
            self.assertFalse(
                list(collision_expected.parent.glob(".current-run.tmp.*"))
            )
            self.assertFalse(
                list(
                    (collision_home / "eks-monitoring-private").glob(
                        ".c010-s4-discovery.*"
                    )
                )
            )
            collision_bytes = collision_identity.read_bytes()
            collision_retry = bind_at(collision_home, first_account)
            self.assertEqual(
                0, collision_retry.returncode, collision_retry.stderr
            )
            self.assertEqual(collision_bytes, collision_identity.read_bytes())

        post_guard = ROOT / "scripts" / "post-guard-verify.sh"
        post_text = post_guard.read_text(encoding="utf-8")
        self.assertLess(
            post_text.index("record_current_sts_identity"),
            post_text.index("aws_zero"),
        )
        self.assertLess(
            post_text.index('aws_zero "Cleanup state machine"'),
            post_text.index('rm -f -- "$CURRENT_STS_IDENTITY_FILE"'),
        )
        self.assertLess(
            post_text.index('rm -f -- "$CURRENT_STS_IDENTITY_FILE"'),
            post_text.index('rmdir -- "$PRIVATE_EXECUTION_DIR"'),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            jq_path = temp_root / "jq"
            jq_path.write_text(JQ_IDENTITY_DOUBLE, encoding="utf-8", newline="\n")
            jq_path.chmod(0o755)
            private_dir = temp_root / "private"
            identity_path = private_dir / "current-sts-identity.json"
            post_argument = shlex.quote(wsl_path(post_guard))
            path_argument = shlex.quote(wsl_path(temp_root))
            private_argument = shlex.quote(wsl_path(private_dir))
            identity_argument = shlex.quote(wsl_path(identity_path))
            account = "123456" + "789012"
            identity = json.dumps(
                {
                    "Account": account,
                    "Arn": f"arn:aws:sts::{account}:assumed-role/example/session",
                    "UserId": "example:session",
                },
                separators=(",", ":"),
            )
            aws_double = (
                "aws() { "
                f"if [[ \"$1 $2\" == 'sts get-caller-identity' ]]; then "
                f"printf '%s\\n' {shlex.quote(identity)}; return 0; fi; "
                "case \"$1 $2\" in "
                "'cloudformation describe-stacks') "
                "printf 'ValidationError: stack does not exist\\n' >&2; return 1 ;; "
                "'eks describe-cluster') "
                "printf 'ResourceNotFoundException\\n' >&2; return 1 ;; "
                "'scheduler get-schedule'|'lambda get-function') "
                "printf 'ResourceNotFoundException\\n' >&2; return 1 ;; "
                "'iam get-role') printf 'NoSuchEntity\\n' >&2; return 1 ;; "
                "esac; "
                "if [[ \"${FAIL_RESIDUAL:-0}\" == 1 && \"$1 $2\" == "
                "'ec2 describe-volumes' ]]; then printf '1\\n'; "
                "else printf '0\\n'; fi; "
                "}; export -f aws; "
            )

            def invoke(fail_residual: bool) -> subprocess.CompletedProcess[str]:
                private_dir.mkdir(exist_ok=True)
                identity_path.write_text(
                    json.dumps(json.loads(identity), sort_keys=True, indent=2) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                return run_bash(
                    f"export PATH={path_argument}:$PATH; "
                    f"export PRIVATE_EXECUTION_DIR={private_argument}; "
                    f"export CURRENT_STS_IDENTITY_FILE={identity_argument}; "
                    f"export FAIL_RESIDUAL={1 if fail_residual else 0}; "
                    f"{aws_double}"
                    f"bash {post_argument}"
                )

            failed = invoke(True)
            self.assertNotEqual(0, failed.returncode)
            self.assertTrue(identity_path.is_file())
            self.assertTrue(private_dir.is_dir())

            passed = invoke(False)
            self.assertEqual(0, passed.returncode, passed.stderr)
            self.assertFalse(identity_path.exists())
            self.assertFalse(private_dir.exists())

    def test_template_parses_and_has_required_resources(self):
        resources = self.template["Resources"]
        types = [resource["Type"] for resource in resources.values()]
        for required in (
            "AWS::EC2::VPC",
            "AWS::EC2::InternetGateway",
            "AWS::EKS::Cluster",
            "AWS::EKS::Nodegroup",
            "AWS::EC2::LaunchTemplate",
        ):
            self.assertIn(required, types)
        self.assertEqual(types.count("AWS::EC2::Subnet"), 2)
        self.assertNotIn("AWS::EC2::NatGateway", types)

    def test_node_join_regression_private_and_restricted_public_endpoints(self):
        config = self.template["Resources"]["EksCluster"]["Properties"]["ResourcesVpcConfig"]
        self.assertIs(config["EndpointPrivateAccess"], True)
        self.assertIs(config["EndpointPublicAccess"], True)
        self.assertEqual(config["PublicAccessCidrs"], ["ApiPublicAccessCidr"])
        self.assertNotIn(
            "0.0.0.0/0",
            str(config["PublicAccessCidrs"]),
        )
        common = self.scripts["common.sh"]
        for token in (
            "endpointPrivateAccess",
            "endpointPublicAccess",
            "publicAccessCidrs must contain exactly one value",
        ):
            self.assertIn(token, common)

    def test_low_cost_deadline_guard_has_private_kubernetes_cleanup_gates(self):
        resources = self.guard_template["Resources"]
        resource_types = {resource["Type"] for resource in resources.values()}
        self.assertNotIn("AWS::EC2::NatGateway", resource_types)
        self.assertNotIn("AWS::EC2::EIP", resource_types)
        self.assertIn("AWS::Lambda::Function", resource_types)
        self.assertIn("AWS::StepFunctions::StateMachine", resource_types)

        schedule = resources["AutomaticCleanupSchedule"]["Properties"]
        self.assertEqual("CleanupStateMachine", schedule["Target"]["Arn"])
        self.assertEqual(
            '{"contract":"udemy4-c010-deadline-cleanup-v2"}',
            schedule["Target"]["Input"],
        )
        scheduler_policy = resources["CleanupSchedulerRole"]["Properties"]["Policies"][
            0
        ]["PolicyDocument"]["Statement"][0]
        self.assertEqual("states:StartExecution", scheduler_policy["Action"])
        self.assertNotIn("cloudformation:DeleteStack", str(scheduler_policy))
        self.assertNotIn(
            "cloudformation:DeleteStack",
            str(resources["CleanupHandlerRole"]),
        )

        definition = json.loads(
            resources["CleanupStateMachine"]["Properties"]["DefinitionString"]
        )
        self.assertEqual(21600, definition["TimeoutSeconds"])
        states = definition["States"]
        exact_log_group_arn = (
            "arn:${AWS::Partition}:logs:ap-northeast-1:${AWS::AccountId}:"
            "log-group:/udemy4/c010/s4/20260725"
        )
        state_machine_statements = resources["CleanupStateMachineRole"]["Properties"][
            "Policies"
        ][0]["PolicyDocument"]["Statement"]
        list_tags_statement = next(
            statement
            for statement in state_machine_statements
            if statement["Action"] == "logs:ListTagsForResource"
        )
        delete_log_statement = next(
            statement
            for statement in state_machine_statements
            if statement["Action"] == "logs:DeleteLogGroup"
        )
        self.assertEqual(exact_log_group_arn, list_tags_statement["Resource"])
        self.assertFalse(list_tags_statement["Resource"].endswith(":*"))
        self.assertEqual(f"{exact_log_group_arn}:*", delete_log_statement["Resource"])
        self.assertTrue(delete_log_statement["Resource"].endswith(":*"))
        self.assertNotIn("logs:ListTagsLogGroup", self.guard_text)
        self.assertNotEqual(f"{exact_log_group_arn}:*", list_tags_statement["Resource"])
        self.assertNotEqual(exact_log_group_arn, delete_log_statement["Resource"])
        self.assertEqual(
            "arn:${AWS::Partition}:states:::aws-sdk:cloudwatchlogs:listTagsForResource",
            states["GetSectionLogTags"]["Resource"],
        )
        self.assertEqual(
            {"ResourceArn": exact_log_group_arn},
            states["GetSectionLogTags"]["Parameters"],
        )
        self.assertLess((ROOT / "cleanup-guard.yaml").stat().st_size, 51200)
        for state in states.values():
            targets = []
            if "Next" in state:
                targets.append(state["Next"])
            if "Default" in state:
                targets.append(state["Default"])
            targets.extend(choice["Next"] for choice in state.get("Choices", []))
            targets.extend(catcher["Next"] for catcher in state.get("Catch", []))
            for target in targets:
                self.assertIn(target, states)
        self.assertEqual("MissingSectionGate", states["MissingSectionGate"]["Error"])
        self.assertEqual("ClassifyCommonStack", states["DescribeCommon"]["Next"])
        self.assertEqual(
            "classify_common_stack",
            states["ClassifyCommonStack"]["Parameters"]["Payload"]["action"],
        )
        classification = states["CommonStackTerminal"]["Choices"]
        self.assertEqual(
            {
                ("terminal", "DescribeCluster"),
                ("pending", "WaitForCommonTerminal"),
            },
            {
                (choice["StringEquals"], choice["Next"])
                for choice in classification
            },
        )
        self.assertEqual(
            "DescribeCommon",
            states["WaitForCommonTerminal"]["Next"],
        )
        self.assertEqual(
            "UnsupportedCommonStatus",
            states["CommonStackTerminal"]["Default"],
        )
        self.assertEqual("DeleteCommon", states["CommonStackKnown"]["Choices"][0]["Next"])
        section_gate = states["SectionGateReady"]["Choices"][0]["And"]
        self.assertEqual(
            {
                "$.section.Payload.section_gate",
                "$.section.Payload.s5_gate",
            },
            {condition["Variable"] for condition in section_gate},
        )
        self.assertEqual(
            "udemy4-c010-deadline-cleanup-v2:s5-kubernetes-absent",
            next(
                condition["StringEquals"]
                for condition in section_gate
                if condition["Variable"] == "$.section.Payload.s5_gate"
            ),
        )
        self.assertIn(
            "udemy4-c010-s5-20260724",
            resources["CleanupHandler"]["Properties"]["Code"]["ZipFile"],
        )
        self.assertEqual(
            "arn:${AWS::Partition}:states:::aws-sdk:cloudformation:deleteStack",
            states["DeleteCommon"]["Resource"],
        )
        self.assertEqual(
            "arn:${AWS::Partition}:states:::aws-sdk:cloudformation:deleteStack",
            states["RemoveGuard"]["Resource"],
        )
        self.assertEqual("RemoveGuard", states["FinalSectionLogAbsent"]["Default"])
        self.assertEqual(
            "DirectDeleteBypass",
            states["DescribeClusterWithoutStack"]["Next"],
        )
        failed_payload = states["ValidateStackWithoutCluster"]["Parameters"]["Payload"]
        self.assertEqual("validate_failed_stack", failed_payload["action"])
        self.assertEqual("SectionAlreadyAbsent", states["ValidateStackWithoutCluster"]["Next"])
        self.assertEqual("ValidateCommon", states["DescribeCluster"]["Next"])
        self.assertEqual(
            "ValidateStackWithoutCluster",
            states["DescribeCluster"]["Catch"][0]["Next"],
        )
        for name in ("DescribeCommon", "DeleteCommon", "PollCommonDelete"):
            self.assertEqual(
                ["CloudFormation.ValidationError"],
                states[name]["Catch"][0]["ErrorEquals"],
            )
        self.assertEqual(
            3,
            self.guard_text.count('"CloudFormation.ValidationError"'),
        )
        self.assertNotIn("CloudFormation.ValidationErrorException", self.guard_text)
        attach = states["AttachCleanupHandler"]["Parameters"]["VpcConfig"]
        self.assertEqual(
            "$.validation.Payload.subnet_ids",
            attach["SubnetIds.$"],
        )
        self.assertEqual(
            {"SubnetIds": [], "SecurityGroupIds": []},
            states["DetachCleanupHandler"]["Parameters"]["VpcConfig"],
        )

        common_resources = self.template["Resources"]
        access = common_resources["CleanupHandlerAccessEntry"]["Properties"]
        self.assertNotIn("AccessPolicies", access)
        self.assertEqual(["udemy4:c010:s4-cleanup"], access["KubernetesGroups"])
        self.assertNotIn(
            "AmazonEKSClusterAdminPolicy", self.text + self.guard_text
        )
        rbac = yaml.safe_load(self.template["Outputs"]["CleanupRbacManifest"]["Value"])
        self.assertEqual("List", rbac["kind"])
        objects = {(item["kind"], item["metadata"]["name"]): item for item in rbac["items"]}
        job_role = objects[("Role", "udemy4-s4-cleanup-job")]
        self.assertEqual("udemy4-s4-logs", job_role["metadata"]["namespace"])
        self.assertEqual(
            [{
                "apiGroups": ["batch"],
                "resources": ["jobs"],
                "resourceNames": ["s4-log-generator"],
                "verbs": ["get", "delete"],
            }],
            job_role["rules"],
        )
        namespace_role = objects[
            ("ClusterRole", "udemy4-c010-s4-cleanup-namespace")
        ]
        self.assertEqual(
            [{
                "apiGroups": [""],
                "resources": ["namespaces"],
                "resourceNames": ["udemy4-s4-logs"],
                "verbs": ["get", "delete"],
            }],
            namespace_role["rules"],
        )
        s5_namespace_role = objects[
            ("ClusterRole", "udemy4-c010-s5-cleanup-namespace")
        ]
        self.assertEqual(
            [{
                "apiGroups": [""],
                "resources": ["namespaces"],
                "resourceNames": ["udemy4-c010-s5-20260724"],
                "verbs": ["get", "delete"],
            }],
            s5_namespace_role["rules"],
        )
        for binding_kind, binding_name, role_kind, role_name in (
            ("RoleBinding", "udemy4-s4-cleanup-job", "Role", "udemy4-s4-cleanup-job"),
            (
                "ClusterRoleBinding",
                "udemy4-c010-s4-cleanup-namespace",
                "ClusterRole",
                "udemy4-c010-s4-cleanup-namespace",
            ),
            (
                "ClusterRoleBinding",
                "udemy4-c010-s5-cleanup-namespace",
                "ClusterRole",
                "udemy4-c010-s5-cleanup-namespace",
            ),
        ):
            binding = objects[(binding_kind, binding_name)]
            self.assertEqual(
                [{
                    "apiGroup": "rbac.authorization.k8s.io",
                    "kind": "Group",
                    "name": "udemy4:c010:s4-cleanup",
                }],
                binding["subjects"],
            )
            self.assertEqual(role_kind, binding["roleRef"]["kind"])
            self.assertEqual(role_name, binding["roleRef"]["name"])

        cluster_rbac = yaml.safe_load(
            self.template["Outputs"]["ClusterCleanupRbacManifest"]["Value"]
        )
        self.assertEqual("List", cluster_rbac["kind"])
        self.assertEqual(
            {
                ("ClusterRole", "udemy4-c010-s4-cleanup-namespace"),
                ("ClusterRoleBinding", "udemy4-c010-s4-cleanup-namespace"),
                ("ClusterRole", "udemy4-c010-s5-cleanup-namespace"),
                ("ClusterRoleBinding", "udemy4-c010-s5-cleanup-namespace"),
            },
            {
                (item["kind"], item["metadata"]["name"])
                for item in cluster_rbac["items"]
            },
        )
        self.assertTrue(
            all(
                item["kind"] in {"ClusterRole", "ClusterRoleBinding"}
                and "namespace" not in item["metadata"]
                for item in cluster_rbac["items"]
            )
        )
        ingress = common_resources["CleanupHandlerEksIngress"]["Properties"]
        self.assertEqual(443, ingress["FromPort"])
        self.assertEqual("CleanupHandlerSecurityGroup", ingress["SourceSecurityGroupId"])

    def test_deadline_handler_behavior_rejects_early_and_direct_delete_invocation(self):
        code = self.guard_template["Resources"]["CleanupHandler"]["Properties"]["Code"][
            "ZipFile"
        ]
        fake_boto3 = types.ModuleType("boto3")
        fake_botocore = types.ModuleType("botocore")
        fake_signers = types.ModuleType("botocore.signers")
        fake_signers.RequestSigner = object
        saved_modules = {
            name: sys.modules.get(name)
            for name in ("boto3", "botocore", "botocore.signers")
        }
        saved_schedule = os.environ.get("SCHEDULE_EXPRESSION")
        try:
            sys.modules["boto3"] = fake_boto3
            sys.modules["botocore"] = fake_botocore
            sys.modules["botocore.signers"] = fake_signers
            os.environ["SCHEDULE_EXPRESSION"] = "at(2999-01-01T00:00:00)"
            early = {}
            exec(compile(code, "cleanup-handler.py", "exec"), early)
            with self.assertRaisesRegex(RuntimeError, "before the exact deadline"):
                early["assert_trigger"](
                    {"contract": "udemy4-c010-deadline-cleanup-v2"}
                )

            os.environ["SCHEDULE_EXPRESSION"] = "at(2020-01-01T00:00:00)"
            post_deadline = {}
            exec(compile(code, "cleanup-handler.py", "exec"), post_deadline)
            failed = post_deadline["validate_failed_stack"](
                self.rollback_fixture["Stacks"][0]
            )
            self.assertEqual("ready", failed["status"])
            for pending in (
                "CREATE_IN_PROGRESS",
                "UPDATE_IN_PROGRESS",
                "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS",
            ):
                creating = copy.deepcopy(self.rollback_fixture["Stacks"][0])
                creating["StackStatus"] = pending
                self.assertEqual(
                    "pending",
                    post_deadline["classify_common_stack"](creating)["status"],
                )
            for terminal in ("CREATE_COMPLETE", "UPDATE_COMPLETE", "ROLLBACK_COMPLETE"):
                terminal_stack = copy.deepcopy(self.rollback_fixture["Stacks"][0])
                terminal_stack["StackStatus"] = terminal
                self.assertEqual(
                    "terminal",
                    post_deadline["classify_common_stack"](terminal_stack)["status"],
                )
            unsupported = copy.deepcopy(self.rollback_fixture["Stacks"][0])
            unsupported["StackStatus"] = "CREATE_FAILED"
            with self.assertRaisesRegex(
                RuntimeError, "unsupported creation status"
            ):
                post_deadline["classify_common_stack"](unsupported)
            for mutation in ("status", "tag", "name"):
                rejected = copy.deepcopy(self.rollback_fixture["Stacks"][0])
                if mutation == "status":
                    rejected["StackStatus"] = "UPDATE_ROLLBACK_COMPLETE"
                elif mutation == "tag":
                    rejected["Tags"].append({"Key": "Unexpected", "Value": "reject"})
                else:
                    rejected["StackName"] = "other"
                with self.assertRaises(RuntimeError):
                    post_deadline["validate_failed_stack"](rejected)
            post_deadline["assert_labels"](
                {
                    "metadata": {
                        "labels": {
                            "course": "c010",
                            "section": "s4",
                            "managed-by": "udemy4",
                            "kubernetes.io/metadata.name": "udemy4-s4-logs",
                        }
                    }
                },
                "Namespace",
            )
            with self.assertRaisesRegex(
                RuntimeError, "Namespace exact ownership labels mismatch"
            ):
                post_deadline["assert_labels"](
                    {
                        "metadata": {
                            "labels": {
                                "course": "c010",
                                "section": "s4",
                                "managed-by": "udemy4",
                                "kubernetes.io/metadata.name": "udemy4-s4-logs",
                                "unexpected-user-label": "reject",
                            }
                        }
                    },
                    "Namespace",
                )
            s5_labels = {
                "app.kubernetes.io/part-of": "udemy4-c010",
                "app.kubernetes.io/managed-by": "udemy4",
                "udemy4.example/course": "C010",
                "udemy4.example/work-package": "issue-31",
                "udemy4.example/purpose": "training",
                "kubernetes.io/metadata.name": "udemy4-c010-s5-20260724",
            }
            post_deadline["assert_s5_labels"](
                {
                    "metadata": {
                        "name": "udemy4-c010-s5-20260724",
                        "labels": copy.deepcopy(s5_labels),
                    }
                }
            )
            with self.assertRaisesRegex(
                RuntimeError, "Section s5 Namespace exact ownership labels mismatch"
            ):
                post_deadline["assert_s5_labels"](
                    {
                        "metadata": {
                            "name": "udemy4-c010-s5-20260724",
                            "labels": {**s5_labels, "unexpected": "reject"},
                        }
                    }
                )
            s5_path = "/api/v1/namespaces/udemy4-c010-s5-20260724"
            calls = []
            s5_present = {"value": True}

            def fake_kube(event, method, path):
                calls.append((method, path))
                if path == s5_path and method == "GET" and s5_present["value"]:
                    return {
                        "metadata": {
                            "name": "udemy4-c010-s5-20260724",
                            "labels": copy.deepcopy(s5_labels),
                        }
                    }
                if path == s5_path and method == "DELETE":
                    s5_present["value"] = False
                    return {}
                return None

            original_kube = post_deadline["kube"]
            post_deadline["kube"] = fake_kube
            cleanup_result = post_deadline["cleanup_section"]({})
            post_deadline["kube"] = original_kube
            self.assertEqual("ready", cleanup_result["status"])
            self.assertEqual(
                "udemy4-c010-deadline-cleanup-v2:s5-kubernetes-absent",
                cleanup_result["s5_gate"],
            )
            self.assertIn(("DELETE", s5_path), calls)
            job_path = (
                "/apis/batch/v1/namespaces/udemy4-s4-logs/jobs/s4-log-generator"
            )
            self.assertFalse(
                any(path == job_path for _, path in calls),
                "An initially absent s4 namespace must cause zero Job endpoint calls.",
            )

            ordered_calls = []
            s4_namespace_path = "/api/v1/namespaces/udemy4-s4-logs"
            s4_present = {"value": True}

            def present_s4_kube(event, method, path):
                ordered_calls.append((method, path))
                if path == s4_namespace_path and method == "GET":
                    if s4_present["value"]:
                        return {
                            "metadata": {
                                "labels": {
                                    "course": "c010",
                                    "section": "s4",
                                    "managed-by": "udemy4",
                                    "kubernetes.io/metadata.name": "udemy4-s4-logs",
                                }
                            }
                        }
                    return None
                if path == job_path and method == "GET":
                    return {
                        "metadata": {
                            "labels": {
                                "course": "c010",
                                "section": "s4",
                                "managed-by": "udemy4",
                            }
                        }
                    }
                if path == s4_namespace_path and method == "DELETE":
                    s4_present["value"] = False
                return None

            post_deadline["kube"] = present_s4_kube
            self.assertEqual(
                "ready",
                post_deadline["cleanup_section"]({})["status"],
            )
            post_deadline["kube"] = original_kube
            namespace_delete_index = ordered_calls.index(
                ("DELETE", s4_namespace_path)
            )
            self.assertEqual(
                [
                    ("GET", s4_namespace_path),
                    ("GET", job_path),
                    ("DELETE", job_path),
                    ("DELETE", s4_namespace_path),
                    ("GET", s4_namespace_path),
                ],
                ordered_calls[: namespace_delete_index + 2],
            )
            self.assertFalse(
                any(
                    path == job_path
                    for _, path in ordered_calls[namespace_delete_index + 1 :]
                ),
                "After namespace absence is established, no Job endpoint may be called.",
            )
            bad_calls = []

            def mismatched_s5_kube(event, method, path):
                bad_calls.append((method, path))
                if path == s5_path and method == "GET":
                    return {
                        "metadata": {
                            "name": "udemy4-c010-s5-20260724",
                            "labels": {**s5_labels, "unexpected": "reject"},
                        }
                    }
                return None

            post_deadline["kube"] = mismatched_s5_kube
            with self.assertRaisesRegex(
                RuntimeError, "Section s5 Namespace exact ownership labels mismatch"
            ):
                post_deadline["cleanup_section"]({})
            post_deadline["kube"] = original_kube
            self.assertNotIn(("DELETE", s5_path), bad_calls)
            with self.assertRaisesRegex(RuntimeError, "direct-delete"):
                post_deadline["handler"](
                    {
                        "contract": "udemy4-c010-deadline-cleanup-v2",
                        "action": "delete_common",
                    },
                    None,
                )
        finally:
            for name, module in saved_modules.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module
            if saved_schedule is None:
                os.environ.pop("SCHEDULE_EXPRESSION", None)
            else:
                os.environ["SCHEDULE_EXPRESSION"] = saved_schedule

    def test_version_gates_use_semantic_behavior(self):
        accepted = run_bash(
            "assert_aws_cli_minimum_text 'aws-cli/2.12.3 Python/3.11'; "
            "assert_aws_cli_minimum_text 'aws-cli/2.13.0 Python/3.11'; "
            "assert_kubectl_minor_compatible v1.31.2 1.30; "
            "assert_kubectl_minor_compatible v1.29.9 1.30"
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        for rejected in (
            "assert_aws_cli_minimum_text 'aws-cli/2.12.2 Python/3.11'",
            "assert_aws_cli_minimum_text 'aws-cli/1.99.99 Python/3.11'",
            "assert_kubectl_minor_compatible v1.32.0 1.30",
            "assert_kubectl_minor_compatible v2.30.0 1.30",
        ):
            result = run_bash(rejected)
            self.assertNotEqual(0, result.returncode, rejected)

    def test_runtime_endpoint_gate_rejects_world_mismatch_and_drift(self):
        accepted = run_bash(
            "assert_runtime_endpoint_values true true 198.51.100.10/32 198.51.100.10/32"
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        for rejected in (
            "assert_runtime_endpoint_values false true 198.51.100.10/32 198.51.100.10/32",
            "assert_runtime_endpoint_values true true 198.51.100.10/32 198.51.100.11/32",
            "assert_runtime_endpoint_values true true 0.0.0.0/0 0.0.0.0/0",
            "assert_runtime_endpoint_values true true 198.51.100.10/32 198.51.100.10/32 198.51.100.11/32",
        ):
            result = run_bash(rejected)
            self.assertNotEqual(0, result.returncode, rejected)

    def test_exact_name_region_and_tags(self):
        for token in (
            'REGION="ap-northeast-1"',
            'STACK_NAME="udemy4-c010-common-20260724"',
            'CLUSTER_NAME="udemy4-c010-common-20260724"',
            '"Course": "C010"',
            '"WorkPackage": "c010-common-eks"',
            '"ManagedBy": "udemy4"',
            '"Purpose": "training"',
            '"TemplateContract"',
        ):
            self.assertIn(token, self.joined)

    def test_exact_tag_maps_are_locale_independent_and_do_not_call_sort(self):
        stack_tags = json.dumps(
            [
                {"Key": "WorkPackage", "Value": "c010-common-eks"},
                {"Key": "TemplateContract", "Value": "udemy4-c010-common-eks-v2-20260724"},
                {"Key": "Purpose", "Value": "training"},
                {"Key": "ManagedBy", "Value": "udemy4"},
                {"Key": "Course", "Value": "C010"},
            ]
        )
        guard_tags = json.dumps(
            [
                {"Key": "WorkPackage", "Value": "c010-common-eks"},
                {"Key": "TemplateContract", "Value": "udemy4-c010-cleanup-guard-v2-20260725"},
                {"Key": "Purpose", "Value": "training-cleanup-guard"},
                {"Key": "ManagedBy", "Value": "udemy4"},
                {"Key": "Course", "Value": "C010"},
            ]
        )
        stack_id = (
            "arn:aws:cloudformation:ap-northeast-1:123456789012:"
            "stack/udemy4-c010-common-20260724/01234567-89ab-cdef-0123-456789abcdef"
        )
        eks_tags = json.dumps(
            {
                "aws:cloudformation:stack-name": "udemy4-c010-common-20260724",
                "aws:cloudformation:stack-id": stack_id,
                "aws:cloudformation:logical-id": "EksCluster",
                "WorkPackage": "c010-common-eks",
                "TemplateContract": "udemy4-c010-common-eks-v2-20260724",
                "Purpose": "training",
                "ManagedBy": "udemy4",
                "Course": "C010",
            }
        )
        result = run_bash(
            "sort() { echo 'external sort must not be called' >&2; return 99; }; "
            "export -f sort; export LC_ALL=C.utf8; "
            f"assert_exact_tag_map {shlex.quote(stack_tags)} stack; "
            f"assert_exact_guard_tag_map {shlex.quote(guard_tags)}; "
            f"assert_exact_eks_cluster_tags {shlex.quote(eks_tags)} {shlex.quote(stack_id)}"
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_api_cidr_has_no_default_and_rejects_world(self):
        cidr = self.template["Parameters"]["ApiPublicAccessCidr"]
        self.assertNotIn("Default", cidr)
        self.assertIn("0\\.0\\.0\\.0/0", cidr["AllowedPattern"])
        self.assertIn('"0.0.0.0/0"', self.scripts["common.sh"])

    def test_one_t3_medium_and_20_gib_gp3(self):
        node = self.template["Resources"]["ManagedNodeGroup"]["Properties"]
        self.assertEqual(node["InstanceTypes"], ["t3.medium"])
        self.assertEqual(
            node["ScalingConfig"],
            {"DesiredSize": 1, "MinSize": 1, "MaxSize": 1},
        )
        ebs = self.template["Resources"]["NodeLaunchTemplate"]["Properties"][
            "LaunchTemplateData"
        ]["BlockDeviceMappings"][0]["Ebs"]
        self.assertEqual(ebs["VolumeSize"], 20)
        self.assertEqual(ebs["VolumeType"], "gp3")
        self.assertTrue(ebs["DeleteOnTermination"])

    def test_minimum_role_policy_set_is_explicit(self):
        cluster = self.template["Resources"]["ClusterRole"]["Properties"]["ManagedPolicyArns"]
        node = self.template["Resources"]["NodeRole"]["Properties"]["ManagedPolicyArns"]
        self.assertEqual(cluster, ["arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"])
        self.assertEqual(
            node,
            [
                "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
                "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPullOnly",
                "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
            ],
        )
        self.assertNotIn('"Action": "*"', self.text)

    def test_guard_precedes_common_and_deadline_is_bounded(self):
        create = self.scripts["create.sh"]
        self.assertLess(
            create.index('--stack-name "$GUARD_STACK_NAME"'),
            create.index('--stack-name "$STACK_NAME"'),
        )
        self.assertLess(
            create.index("get_expected_guard_binding"),
            create.index('--stack-name "$STACK_NAME"'),
        )
        self.assertEqual(2, create.count("cloudformation create-stack"))
        self.assertEqual(2, create.count("cloudformation wait stack-create-complete"))
        self.assertNotIn("cloudformation deploy", create)
        self.assertNotIn("cloudformation update-stack", create)
        self.assertIn("AlreadyExistsException", create)
        self.assertIn("refusing to update or adopt", create)
        self.assertNotIn("delete-stack", create)
        update_scripts = [
            name
            for name, body in self.scripts.items()
            if "cloudformation update-stack" in body
        ]
        self.assertEqual(["recover-cidr.sh"], update_scripts)
        common = self.scripts["common.sh"]
        for token in (
            "CLEANUP_DEADLINE_UTC",
            "datetime.timedelta(minutes=15)",
            "datetime.timedelta(hours=6)",
            "AVAILABILITY_ZONE_A",
            "AVAILABILITY_ZONE_B",
            "No EKS cluster quota headroom",
        ):
            self.assertIn(token, common)

    def test_create_applies_and_reads_back_exact_cluster_cleanup_rbac(self):
        create = self.scripts["create.sh"]
        self.assertLess(
            create.index("assert_exact_kubernetes_context"),
            create.index("apply_exact_cluster_cleanup_rbac"),
        )
        self.assertLess(
            create.index("apply_exact_cluster_cleanup_rbac"),
            create.index("kubectl wait"),
        )
        common = self.scripts["common.sh"]
        for token in (
            "ClusterCleanupRbacManifest",
            'printf \'%s\\n\' "$CLUSTER_CLEANUP_RBAC_MANIFEST" | kubectl apply -f -',
            'kubectl get clusterrole "$name" -o json',
            'kubectl get clusterrolebinding "$name" -o json',
            '"resourceNames": [$namespace]',
            '"name": "udemy4:c010:s4-cleanup"',
        ):
            self.assertIn(token, common)

        role_json = json.dumps(
            {
                "kind": "ClusterRole",
                "metadata": {
                    "name": "placeholder",
                    "labels": {
                        "course": "c010",
                        "managed-by": "udemy4",
                        "section": "placeholder",
                    },
                },
                "rules": [
                    {
                        "apiGroups": [""],
                        "resourceNames": ["placeholder"],
                        "resources": ["namespaces"],
                        "verbs": ["get", "delete"],
                    }
                ],
            },
            separators=(",", ":"),
        )
        binding_json = json.dumps(
            {
                "kind": "ClusterRoleBinding",
                "metadata": {
                    "name": "placeholder",
                    "labels": {
                        "course": "c010",
                        "managed-by": "udemy4",
                        "section": "placeholder",
                    },
                },
                "roleRef": {
                    "apiGroup": "rbac.authorization.k8s.io",
                    "kind": "ClusterRole",
                    "name": "placeholder",
                },
                "subjects": [
                    {
                        "apiGroup": "rbac.authorization.k8s.io",
                        "kind": "Group",
                        "name": "udemy4:c010:s4-cleanup",
                    }
                ],
            },
            separators=(",", ":"),
        )
        manifest = self.template["Outputs"]["ClusterCleanupRbacManifest"]["Value"]
        result = run_bash(
            "assert_exact_kubernetes_context(){ :; }; "
            f"export CLUSTER_CLEANUP_RBAC_MANIFEST={shlex.quote(manifest)}; "
            f"ROLE_FIXTURE={shlex.quote(role_json)}; "
            f"BINDING_FIXTURE={shlex.quote(binding_json)}; "
            "jq(){ "
            "local name='' section='' namespace=''; "
            "while (($#)); do "
            "if [[ \"$1\" == --arg ]]; then "
            "case \"$2\" in name) name=\"$3\";; section) section=\"$3\";; namespace) namespace=\"$3\";; esac; "
            "shift 3; else shift; fi; done; "
            "python3 -c 'import json,sys; d=json.load(sys.stdin); name,section,namespace=sys.argv[1:]; "
            "assert d[\"metadata\"][\"name\"]==name; "
            "assert d[\"metadata\"][\"labels\"]=={\"course\":\"c010\",\"managed-by\":\"udemy4\",\"section\":section}; "
            "expected=([{\"apiGroups\":[\"\"],\"resourceNames\":[namespace],\"resources\":[\"namespaces\"],\"verbs\":[\"get\",\"delete\"]}] "
            "if d[\"kind\"]==\"ClusterRole\" else None); "
            "assert (d[\"rules\"]==expected if expected is not None else "
            "(d[\"kind\"]==\"ClusterRoleBinding\" and d[\"roleRef\"]=={\"apiGroup\":\"rbac.authorization.k8s.io\",\"kind\":\"ClusterRole\",\"name\":name} "
            "and d[\"subjects\"]==[{\"apiGroup\":\"rbac.authorization.k8s.io\",\"kind\":\"Group\",\"name\":\"udemy4:c010:s4-cleanup\"}]))' "
            "\"$name\" \"$section\" \"$namespace\"; "
            "}; "
            "kubectl(){ "
            "if [[ \"$1\" == apply ]]; then "
            "payload=\"$(cat)\"; "
            "[[ \"$payload\" != *$'kind: Namespace'* && \"$payload\" != *$'kind: Role\\n'* && \"$payload\" != *$'kind: RoleBinding\\n'* ]]; "
            "return; "
            "fi; "
            "local kind=\"$2\" name=\"$3\" section namespace fixture; "
            "if [[ \"$name\" == *s4* ]]; then section=s4; namespace=udemy4-s4-logs; "
            "else section=s5; namespace=udemy4-c010-s5-20260724; fi; "
            "if [[ \"$kind\" == clusterrole ]]; then fixture=\"$ROLE_FIXTURE\"; "
            "else fixture=\"$BINDING_FIXTURE\"; fi; "
            "python3 -c 'import json,sys; d=json.loads(sys.argv[1]); name,section,namespace=sys.argv[2:]; "
            "d[\"metadata\"][\"name\"]=name; d[\"metadata\"][\"labels\"][\"section\"]=section; "
            "(d[\"rules\"][0].update(resourceNames=[namespace]) if d[\"kind\"]==\"ClusterRole\" else d[\"roleRef\"].update(name=name)); "
            "print(json.dumps(d,separators=(\",\",\":\")))' "
            "\"$fixture\" \"$name\" \"$section\" \"$namespace\"; "
            "}; "
            "apply_exact_cluster_cleanup_rbac"
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_cloudshell_cidr_recovery_is_exact_and_non_adopting(self):
        recovery = self.scripts["recover-cidr.sh"]
        for token in (
            "get_expected_guard_binding",
            "Existing runtime endpoint does not match",
            "Common stack parameter set mismatch",
            "ParameterKey=$key,ParameterValue=$new_cidr",
            "UsePreviousValue=true",
            "cloudformation update-stack",
            "cloudformation wait stack-update-complete",
            "get_expected_stack_binding",
            "assert_exact_kubernetes_context",
        ):
            self.assertIn(token, recovery)
        self.assertLess(
            recovery.index("assert_exact_tag_map"),
            recovery.index("cloudformation update-stack"),
        )
        self.assertLess(
            recovery.index("cloudformation wait stack-update-complete"),
            recovery.index("get_expected_stack_binding"),
        )
        accepted = run_bash(
            "assert_runtime_endpoint_values true true 198.51.100.10/32 198.51.100.10/32"
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        for rejected in (
            "assert_runtime_endpoint_values true true 198.51.100.10/32 0.0.0.0/0",
            "assert_runtime_endpoint_values true true 198.51.100.10/32 198.51.100.10/32 198.51.100.11/32",
        ):
            self.assertNotEqual(0, run_bash(rejected).returncode)

    def test_rollback_complete_fixture_and_manual_recovery_are_fail_closed(self):
        fixture = json.dumps(self.rollback_fixture, separators=(",", ":"))
        accepted = run_bash(
            f"assert_failed_stack_document {shlex.quote(fixture)} >/dev/null; "
            "aws_exact_not_found(){ return 0; }; "
            f"get_failed_stack_binding {shlex.quote(fixture)}; "
            "require_common_cleanup_gate"
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        active_cluster = run_bash(
            "aws_exact_not_found(){ return 1; }; "
            f"get_failed_stack_binding {shlex.quote(fixture)}"
        )
        self.assertNotEqual(0, active_cluster.returncode)
        for mutation in ("status", "tag", "name"):
            rejected = copy.deepcopy(self.rollback_fixture)
            stack = rejected["Stacks"][0]
            if mutation == "status":
                stack["StackStatus"] = "UPDATE_ROLLBACK_COMPLETE"
            elif mutation == "tag":
                stack["Tags"].append({"Key": "Unexpected", "Value": "reject"})
            else:
                stack["StackName"] = "other"
            result = run_bash(
                f"assert_failed_stack_document {shlex.quote(json.dumps(rejected))}"
            )
            self.assertNotEqual(0, result.returncode, mutation)

        delete = self.scripts["delete.sh"]
        self.assertIn('[[ "$status" == "ROLLBACK_COMPLETE" ]]', delete)
        self.assertIn('get_failed_stack_binding "$stacks"', delete)
        self.assertLess(
            delete.index('get_failed_stack_binding "$stacks"'),
            delete.index("cloudformation delete-stack"),
        )
        self.assertLess(
            delete.index("cloudformation wait stack-delete-complete"),
            delete.index('source "$SCRIPT_DIR/verify-cleanup.sh"'),
        )
        self.assertIn("require_common_cleanup_gate", self.scripts["verify-cleanup.sh"])

    def test_cleanup_is_fail_closed_and_guard_is_removed_last(self):
        verify = self.scripts["verify-cleanup.sh"]
        for token in (
            "describe-stacks",
            "describe-cluster",
            "describe-instances",
            "describe-volumes",
            "describe-network-interfaces",
            "describe-log-groups",
            "Cleanup verification failed closed",
            "get_expected_guard_binding",
            "scheduler get-schedule",
            "Section s4 log group remains",
            "require_common_cleanup_gate",
            "must only be sourced by delete.sh",
        ):
            self.assertIn(token, verify)
        self.assertLess(
            verify.index('[[ "${BASH_SOURCE[0]}" == "$0" ]]'),
            verify.index("require_common_cleanup_gate"),
        )
        self.assertLess(
            verify.index("if ((${#failures[@]}))"),
            verify.index("get_expected_guard_binding"),
        )
        self.assertLess(
            verify.index("get_expected_guard_binding"),
            verify.index("cloudformation delete-stack"),
        )
        common = self.scripts["common.sh"]
        delete = self.scripts["delete.sh"]
        for token in (
            "kubectl get namespace udemy4-s4-logs",
            'select(.logGroupName == "/udemy4/c010/s4/20260725")',
            "SECTION_S4_CLEANUP_GATE_PASSED",
            "kubectl get namespace udemy4-c010-s5-20260724",
            "SECTION_S5_CLEANUP_GATE_PASSED",
        ):
            self.assertIn(token, common)
        self.assertNotIn(
            "kubectl get job s4-log-generator -n udemy4-s4-logs",
            common,
        )
        self.assertLess(
            delete.index("assert_section_s4_residuals_absent"),
            delete.index("cloudformation delete-stack"),
        )
        self.assertLess(
            delete.index("assert_section_s5_residuals_absent"),
            delete.index("cloudformation delete-stack"),
        )
        self.assertLess(
            delete.index("cloudformation wait stack-delete-complete"),
            delete.index('source "$SCRIPT_DIR/verify-cleanup.sh"'),
        )

    def test_cleanup_gate_cannot_be_skipped_or_replayed_for_another_binding(self):
        result = run_bash(
            "export API_PUBLIC_ACCESS_CIDR=198.51.100.10/32; "
            "printf -v expected '%s|%s|%s|%s|%s' "
            '"$REGION" "$CLUSTER_NAME" "$API_PUBLIC_ACCESS_CIDR" '
            "'udemy4-s4-logs' '/udemy4/c010/s4/20260725'; "
            "unset SECTION_S4_CLEANUP_GATE_PASSED; "
            "if require_section_s4_cleanup_gate; then exit 20; fi; "
            "SECTION_S4_CLEANUP_GATE_PASSED='wrong-binding'; "
            "if require_section_s4_cleanup_gate; then exit 21; fi; "
            "SECTION_S4_CLEANUP_GATE_PASSED=$expected; "
            "require_section_s4_cleanup_gate"
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_s5_cleanup_gate_rejects_remaining_namespace_and_binds_not_found(self):
        remains = run_bash(
            "export API_PUBLIC_ACCESS_CIDR=198.51.100.10/32; "
            "assert_exact_kubernetes_context() { :; }; "
            "kubectl() { printf 'namespace/udemy4-c010-s5-20260724\\n'; }; "
            "assert_section_s5_residuals_absent"
        )
        self.assertNotEqual(0, remains.returncode)
        self.assertIn("Section s5 namespace remains", remains.stderr)

        absent = run_bash(
            "export API_PUBLIC_ACCESS_CIDR=198.51.100.10/32; "
            "assert_exact_kubernetes_context() { :; }; "
            "kubectl() { printf 'Error from server (NotFound)\\n' >&2; return 1; }; "
            "assert_section_s5_residuals_absent; "
            "require_section_s5_cleanup_gate"
        )
        self.assertEqual(0, absent.returncode, absent.stderr)

    def test_common_cleanup_requires_both_s4_and_s5_gates(self):
        common = self.scripts["common.sh"]
        self.assertLess(
            common.index("require_section_s4_cleanup_gate", common.index("require_common_cleanup_gate")),
            common.index("require_section_s5_cleanup_gate", common.index("require_common_cleanup_gate")),
        )
        result = run_bash(
            "export API_PUBLIC_ACCESS_CIDR=198.51.100.10/32; "
            "SECTION_S4_CLEANUP_GATE_PASSED=\"$(section_s4_cleanup_gate_binding)\"; "
            "unset SECTION_S5_CLEANUP_GATE_PASSED; "
            "if require_common_cleanup_gate; then exit 31; fi; "
            "SECTION_S5_CLEANUP_GATE_PASSED=\"$(section_s5_cleanup_gate_binding)\"; "
            "require_common_cleanup_gate"
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_explicit_not_found_rejects_permission_and_network_errors(self):
        common = self.scripts["common.sh"]
        for token in (
            "aws_exact_not_found",
            "AccessDenied",
            "Unauthorized",
            "ExpiredToken",
            "InvalidClientToken",
            "Could not connect",
        ):
            self.assertIn(token, common)

    def test_no_dangerous_wildcard_delete(self):
        self.assertNotRegex(
            self.joined,
            r"\b(delete|remove)[^\n]*(--all|\*|all-resources)",
        )
        self.assertNotIn(
            "0.0.0.0/0",
            self.template["Resources"]["EksCluster"]["Properties"][
                "ResourcesVpcConfig"
            ]["PublicAccessCidrs"],
        )

    def test_readme_has_cost_cleanup_and_official_sources(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for token in (
            "4時間",
            "最大6時間",
            "約USD 0.97",
            "実請求",
            "scripts/delete.sh",
            "scripts/verify-cleanup.sh",
            "Section 4",
            "guardを最後",
        ):
            self.assertIn(token, readme)
        urls = re.findall(r"https://[^)]+", readme)
        self.assertTrue(urls)
        self.assertTrue(
            all(
                url.startswith(("https://aws.amazon.com/", "https://docs.aws.amazon.com/"))
                or url.startswith("https://checkip.amazonaws.com")
                for url in urls
            )
        )

    def test_canonical_inventory_is_byte_ordinal_and_exact(self):
        repository = ROOT.parents[1]
        inventory_path = ROOT / "artifact-inventory.sha256"
        records = [
            line
            for line in inventory_path.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")
        ]
        paths = [record.split("  ", 1)[1] for record in records]
        self.assertEqual(paths, sorted(paths, key=lambda value: value.encode("utf-8")))
        discovered = []
        for package in (ROOT, ROOT.parent / "s5-pod-resource-first-response"):
            for path in package.rglob("*"):
                relative = path.relative_to(repository).as_posix()
                if not path.is_file():
                    continue
                if (
                    path == inventory_path
                    or "review-evidence" in path.parts
                    or "__pycache__" in path.parts
                ):
                    continue
                if path.name.startswith("public-repository-preparation-"):
                    continue
                discovered.append(relative)
        self.assertEqual(paths, sorted(discovered, key=lambda value: value.encode("utf-8")))
        for record in records:
            expected_hash, relative = record.split("  ", 1)
            actual_hash = hashlib.sha256((repository / relative).read_bytes()).hexdigest()
            self.assertEqual(expected_hash, actual_hash, relative)


if __name__ == "__main__":
    unittest.main()
