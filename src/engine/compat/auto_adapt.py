"""Build a new isolated Codex compatibility runtime when anchors still match.

The official AppX installation is read only. A failed adaptation removes only
its staging directory and leaves every previously verified runtime untouched.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--builder", required=True, type=Path)
    parser.add_argument("--node", required=True)
    args = parser.parse_args()

    source = args.source.resolve()
    root = args.root.resolve()
    target = root / args.version
    receipt_path = target / "verification.json"
    if receipt_path.exists():
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if Path(str(receipt.get("source", ""))).resolve() == source:
                print(json.dumps({"status": "already_ready", "version": args.version, "runtime": str(target / "runtime")}))
                return 0
        except (OSError, ValueError):
            pass
        raise RuntimeError(f"Refusing to overwrite an existing incompatible release: {target}")
    if not source.is_dir():
        raise RuntimeError(f"Official source directory not found: {source}")
    if not args.builder.is_file():
        raise RuntimeError(f"Adapter source not found: {args.builder}")
    root.mkdir(parents=True, exist_ok=True)
    stage = root / f".staging-{args.version}-{os.getpid()}"
    if stage.exists():
        shutil.rmtree(stage)
    try:
        # Reviewed builders in order; the first whose anchors match the installed version wins.
        builders = [args.builder]
        details = []
        for builder in builders:
            if not builder.is_file():
                continue
            if stage.exists():
                shutil.rmtree(stage)
            command = [sys.executable, str(builder), "--source", str(source), "--output", str(stage), "--node", args.node, "--build"]
            completed = subprocess.run(command, check=False, capture_output=True, text=True)
            if completed.returncode == 0:
                args.builder = builder
                break
            details.append((completed.stderr or completed.stdout or "adapter failed").strip()[-400:])
        else:
            raise RuntimeError(" | ".join(details)[-1200:])
        generated = stage / "verification.json"
        if not generated.is_file():
            raise RuntimeError("Adapter did not produce verification.json")
        receipt = json.loads(generated.read_text(encoding="utf-8"))
        if receipt.get("integrityRetained") is not True or receipt.get("officialInstallationModified") is not False:
            raise RuntimeError("Adapter verification did not prove isolated integrity")
        receipt["runtime"] = str(target / "runtime")
        receipt["sourceScript"] = str(args.builder.resolve())
        generated.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        stage.rename(target)
        print(json.dumps({"status": "adapted", "version": args.version, "runtime": str(target / "runtime"), "checks": receipt.get("checks")}))
        return 0
    except Exception:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        raise


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "not_adapted", "detail": str(exc)}))
        raise SystemExit(2)
