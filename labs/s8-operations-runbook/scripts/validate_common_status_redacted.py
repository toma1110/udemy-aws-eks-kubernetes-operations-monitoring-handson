#!/usr/bin/env python3
"""Run the common status dependency without exposing its success stdout."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


def validate_common_status(common_dir: Path, private_dir: Path) -> int:
    if not common_dir.is_absolute():
        print("ERROR: COMMON_EKS_DIR must be an absolute path.", file=sys.stderr)
        return 1
    if not private_dir.is_absolute() or not private_dir.is_dir():
        print(
            "ERROR: S8_PRIVATE_DIR must be an existing private directory.",
            file=sys.stderr,
        )
        return 1

    status_script = common_dir / "scripts" / "status.sh"
    if not status_script.is_file():
        print(
            "ERROR: The common EKS status dependency is missing.",
            file=sys.stderr,
        )
        return 1

    output_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix="common-status.",
            dir=private_dir,
            delete=False,
        ) as output:
            output_path = Path(output.name)
            os.chmod(output_path, stat.S_IRUSR | stat.S_IWUSR)
            result = subprocess.run(
                [str(status_script)],
                stdout=output,
                check=False,
            )
        if result.returncode != 0:
            print(
                "ERROR: Common EKS status validation failed; "
                "use the diagnostic above.",
                file=sys.stderr,
            )
            return 1
        print("Common EKS status validation passed.")
        return 0
    finally:
        if output_path is not None:
            output_path.unlink(missing_ok=True)


def main() -> int:
    common_raw = os.environ.get("COMMON_EKS_DIR", "")
    private_raw = os.environ.get("S8_PRIVATE_DIR", "")
    return validate_common_status(Path(common_raw), Path(private_raw))


if __name__ == "__main__":
    raise SystemExit(main())
