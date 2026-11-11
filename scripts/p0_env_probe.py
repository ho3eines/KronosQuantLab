"""P0.1 - Read-only environment probe for Kronos Quant Lab.

Standard library only: run it with the system Python *before* creating a venv
or installing anything. It changes nothing on the system; it only writes one
timestamped JSON report (never overwriting an earlier one).

Usage (Windows):  py scripts\\p0_env_probe.py
Usage (other):    python3 scripts/p0_env_probe.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import platform
import shutil
import string
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO_ROOT / "artifacts" / "reports"


def run(cmd: list[str], timeout: int = 30) -> dict[str, Any]:
    """Run a command, never raising; a missing tool is a result, not a crash."""
    if shutil.which(cmd[0]) is None:
        return {"available": False, "error": f"{cmd[0]} not found on PATH"}
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, errors="replace"
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": True, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "available": True,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip()[:2000],
    }


def powershell_json(expression: str) -> Any:
    """Evaluate a read-only PowerShell CIM query and parse its JSON output."""
    res = run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         f"{expression} | ConvertTo-Json -Compress"]
    )
    if res.get("returncode") != 0 or not res.get("stdout"):
        return res
    try:
        return json.loads(res["stdout"])
    except json.JSONDecodeError:
        return res


def python_info() -> dict[str, Any]:
    return {
        "version": sys.version,
        "executable": sys.executable,
        "pointer_bits": struct.calcsize("P") * 8,
        "implementation": platform.python_implementation(),
        "in_virtualenv": sys.prefix != sys.base_prefix,
        "pip": run([sys.executable, "-m", "pip", "--version"]),
        "venv_module": run([sys.executable, "-c", "import venv, ensurepip; print('ok')"]),
        "py_launcher_list": run(["py", "-0p"]) if os.name == "nt" else None,
    }


def os_info() -> dict[str, Any]:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "platform": platform.platform(),
    }


def cpu_ram_gpu_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "logical_cpus": os.cpu_count(),
        "processor": platform.processor(),
    }
    if os.name == "nt":
        info["cpu"] = powershell_json(
            "Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,"
            "NumberOfLogicalProcessors,MaxClockSpeed"
        )
        info["ram"] = powershell_json(
            "Get-CimInstance Win32_OperatingSystem | Select-Object "
            "TotalVisibleMemorySize,FreePhysicalMemory"
        )  # values are in KiB
        info["video_controllers"] = powershell_json(
            "Get-CimInstance Win32_VideoController | Select-Object Name,"
            "DriverVersion,DriverDate,AdapterRAM"
        )  # AdapterRAM is a 32-bit field and may under-report
    else:
        try:
            meminfo = Path("/proc/meminfo").read_text().splitlines()[:3]
            cpu = [
                line for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")
            ]
            info["meminfo"] = meminfo
            info["cpu"] = cpu[0] if cpu else None
        except OSError as exc:
            info["error"] = str(exc)
    # Only reports what the driver says; says nothing about PyTorch compatibility.
    info["nvidia_smi"] = run([
        "nvidia-smi",
        "--query-gpu=name,driver_version,memory.total,memory.used",
        "--format=csv,noheader",
    ])
    return info


def disk_info() -> list[dict[str, Any]]:
    if os.name == "nt":
        roots = [f"{c}:\\" for c in string.ascii_uppercase if os.path.exists(f"{c}:\\")]
    else:
        roots = ["/", str(Path.home())]
    roots.append(str(REPO_ROOT))
    out = []
    for root in dict.fromkeys(roots):
        try:
            u = shutil.disk_usage(root)
            out.append({
                "path": root,
                "total_gb": round(u.total / 1024**3, 2),
                "free_gb": round(u.free / 1024**3, 2),
            })
        except OSError as exc:
            out.append({"path": root, "error": str(exc)})
    return out


def torch_info() -> dict[str, Any]:
    """Report torch only if it already happens to be installed; never install."""
    try:
        import torch  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001 - broken installs raise many types
        return {"installed": False, "detail": f"{type(exc).__name__}: {exc}"}
    info: dict[str, Any] = {"installed": True, "version": torch.__version__}
    try:
        info["cuda_built"] = torch.version.cuda
        info["cuda_available"] = bool(torch.cuda.is_available())
        if info["cuda_available"]:
            info["device"] = torch.cuda.get_device_name(0)
            info["capability"] = list(torch.cuda.get_device_capability(0))
    except Exception as exc:  # noqa: BLE001
        info["cuda_error"] = f"{type(exc).__name__}: {exc}"
    return info


def collect() -> dict[str, Any]:
    return {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "repo_root": str(REPO_ROOT),
        "os": os_info(),
        "python": python_info(),
        "hardware": cpu_ram_gpu_info(),
        "disks": disk_info(),
        "git": run(["git", "--version"]),
        "torch": torch_info(),
    }


def main() -> int:
    report = collect()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = REPORT_DIR / f"p0_env_{stamp}.json"
    with path.open("x", encoding="utf-8") as fh:  # "x": refuse to overwrite
        json.dump(report, fh, indent=2, ensure_ascii=False)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nSaved: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
