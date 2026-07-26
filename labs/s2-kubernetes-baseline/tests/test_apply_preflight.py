import pathlib
import shlex
import shutil
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


def wsl_path(path):
    return subprocess.check_output(
        ["bash", "-lc", f"wslpath -a {shlex.quote(str(path))}"],
        text=True,
    ).strip()


COMMON_STUB = """\
#!/usr/bin/env bash
set -euo pipefail
readonly S2_NAMESPACE="udemy4-c010-s2-baseline"
readonly S2_LAB="s2-baseline"
die() { printf '%s\n' "$*" >&2; exit 1; }
assert_s2_target() { :; }
assert_exact_s2_namespace() {
  [[ "${SCENARIO:-}" != "identity-fails" ]] ||
    die "New Namespace identity validation failed."
}
"""


KUBECTL_STUB = r"""#!/usr/bin/env python3
import json
import os
import pathlib
import sys

args = sys.argv[1:]
scenario = os.environ["SCENARIO"]
mutation_log = pathlib.Path(os.environ["MUTATION_LOG"])
namespace_created = pathlib.Path(os.environ["NAMESPACE_CREATED"])

def fail(message):
    print(message, file=sys.stderr)
    raise SystemExit(1)

if args[:2] == ["get", "namespace"]:
    if not namespace_created.exists():
        failures = {
            "forbidden": "Error from server (Forbidden)",
            "unauthorized": "You must be logged in (Unauthorized)",
            "wrong-context": "context does not match expected cluster",
            "network": "Unable to connect to the server",
        }
        if scenario in failures:
            fail(failures[scenario])
        if scenario == "mixed-text":
            print("NotFound text mixed with transport failure")
            raise SystemExit(0)
        if scenario == "existing":
            print(json.dumps({"metadata": {"name": "udemy4-c010-s2-baseline"}}))
        raise SystemExit(0)
    print(json.dumps({
        "metadata": {
            "name": "udemy4-c010-s2-baseline",
            "labels": {
                "app.kubernetes.io/part-of": "udemy4-c010",
                "app.kubernetes.io/managed-by": "udemy4",
                "udemy4.example/course": "C010",
                "udemy4.example/lab": "s2-baseline",
                "udemy4.example/purpose": "training",
            },
        },
    }))
    raise SystemExit(0)

if args and args[0] in {"create", "apply", "delete", "patch", "replace"}:
    manifest = pathlib.Path(args[-1]).name
    with mutation_log.open("a", encoding="utf-8") as stream:
        stream.write(f"{args[0]}:{manifest}\n")
    if manifest == "00-namespace.yaml":
        if scenario == "namespace-create-fails":
            fail("namespace create failed")
        namespace_created.write_text("created", encoding="utf-8")
    raise SystemExit(0)

if args[:2] == ["rollout", "status"]:
    raise SystemExit(0)

if args[:3] == ["get", "deployment", "baseline-web"]:
    print(json.dumps({
        "metadata": {
            "labels": {
                "udemy4.example/lab": "s2-baseline",
            },
        },
        "spec": {"replicas": 1},
        "status": {"readyReplicas": 1},
    }))
    raise SystemExit(0)

if args[:3] == ["get", "service", "baseline-web"]:
    print(json.dumps({
        "spec": {
            "type": "ClusterIP",
            "selector": {
                "app.kubernetes.io/name": "baseline-web",
                "udemy4.example/lab": "s2-baseline",
            },
        },
    }))
    raise SystemExit(0)

raise SystemExit(0)
"""


class ApplyPreflightRegressionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.scripts = self.root / "scripts"
        self.manifests = self.root / "manifests"
        self.bin = self.root / "bin"
        for directory in (self.scripts, self.manifests, self.bin):
            directory.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "scripts" / "apply-workload.sh", self.scripts)
        (self.scripts / "common.sh").write_text(
            COMMON_STUB, encoding="utf-8", newline="\n"
        )
        for name in ("00-namespace.yaml", "10-deployment.yaml", "20-service.yaml"):
            (self.manifests / name).write_text("stub\n", encoding="utf-8")
        (self.bin / "kubectl").write_text(
            KUBECTL_STUB, encoding="utf-8", newline="\n"
        )
        (self.bin / "jq").write_text(
            "#!/usr/bin/env bash\nexit 0\n", encoding="utf-8", newline="\n"
        )
        for path in list(self.scripts.glob("*.sh")) + list(self.bin.iterdir()):
            path.chmod(0o755)
        self.mutation_log = self.root / "mutations.log"
        self.namespace_created = self.root / "namespace-created"

    def tearDown(self):
        self.temp.cleanup()

    def run_apply(self, scenario):
        env = {
            "PATH": f"{wsl_path(self.bin)}:/usr/bin:/bin",
            "SCENARIO": scenario,
            "MUTATION_LOG": wsl_path(self.mutation_log),
            "NAMESPACE_CREATED": wsl_path(self.namespace_created),
        }
        command = "env " + " ".join(
            f"{key}={shlex.quote(value)}" for key, value in env.items()
        )
        command += (
            " bash "
            + shlex.quote(wsl_path(self.scripts / "apply-workload.sh"))
        )
        return subprocess.run(
            ["bash", "-lc", command],
            text=True,
            capture_output=True,
            timeout=20,
        )

    def mutations(self):
        if not self.mutation_log.exists():
            return []
        return self.mutation_log.read_text(encoding="utf-8").splitlines()

    def test_existing_or_untrusted_namespace_observation_blocks_all_mutation(self):
        for scenario in (
            "existing",
            "forbidden",
            "unauthorized",
            "wrong-context",
            "network",
            "mixed-text",
        ):
            with self.subTest(scenario=scenario):
                self.mutation_log.unlink(missing_ok=True)
                result = self.run_apply(scenario)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual([], self.mutations())

    def test_exact_absence_creates_resources_in_order(self):
        result = self.run_apply("absent")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(
            [
                "create:00-namespace.yaml",
                "create:10-deployment.yaml",
                "create:20-service.yaml",
            ],
            self.mutations(),
        )

    def test_create_or_identity_failure_stops_later_mutations(self):
        for scenario in ("namespace-create-fails", "identity-fails"):
            with self.subTest(scenario=scenario):
                self.mutation_log.unlink(missing_ok=True)
                self.namespace_created.unlink(missing_ok=True)
                result = self.run_apply(scenario)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(["create:00-namespace.yaml"], self.mutations())


if __name__ == "__main__":
    unittest.main()
