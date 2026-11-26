"""Validate the native Windows app in an isolated scratch directory.

Run with Windows Python. --bootstrap-node downloads a verified portable Node.js
when it is not installed. No global packages or real ledger data are used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NODE_VERSION = "24.22.3"


def download(url: str, target: Path) -> None:
    with urllib.request.urlopen(url, timeout=90) as response, target.open("wb") as stream:
        shutil.copyfileobj(response, stream)


def portable_node(work: Path) -> Path:
    arch = "arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "x64"
    name = f"node-v{NODE_VERSION}-win-{arch}"
    tools = work / "tools"
    tools.mkdir(exist_ok=True)
    binary = tools / name / "node.exe"
    if binary.exists():
        return binary
    print("[Windows] Downloading verified portable Node.js", flush=True)
    base = f"https://nodejs.org/dist/v{NODE_VERSION}/"
    checksums, archive = tools / "SHASUMS256.txt", tools / f"{name}.zip"
    download(base + "SHASUMS256.txt", checksums)
    download(base + archive.name, archive)
    expected = next(line.split()[0] for line in checksums.read_text("utf-8").splitlines()
                    if line.split()[-1] == archive.name)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise RuntimeError("Node.js archive checksum mismatch")
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            (tools / member.filename).resolve().relative_to(tools.resolve())
        package.extractall(tools)
    return binary


def run(label: str, command: list[str], cwd: Path, environment: dict[str, str], logs: Path) -> None:
    print(f"[Windows] {label}", flush=True)
    log = logs / (label.replace(" ", "-").lower() + ".log")
    with log.open("w", encoding="utf-8") as stream:
        completed = subprocess.run(command, cwd=cwd, env=environment, stdout=stream,
                                   stderr=subprocess.STDOUT, timeout=900)
    if completed.returncode:
        print(log.read_text("utf-8", errors="replace")[-12000:], flush=True)
        raise RuntimeError(f"{label} failed ({completed.returncode}); log: {log}")
    print(f"[Windows] {label}: passed", flush=True)


def archive_bundle(executable: Path, destination: Path) -> dict:
    """Package the verified runtime; user data never belongs in a release archive."""
    folder, destination = executable.parent.resolve(), destination.resolve()
    if destination.is_relative_to(folder):
        raise RuntimeError("The zip destination must be outside the application bundle")
    if not executable.is_file():
        raise FileNotFoundError(executable)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as package:
        for source in sorted(folder.rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(folder)
            if relative.parts[0].lower() == "data" or source.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
                continue
            package.write(source, "StockLedger/" + relative.as_posix())
        package.writestr("StockLedger/START-HERE.txt", (
            "Stock Ledger\n\n"
            "Extract this entire folder, then open Stock Ledger.exe.\n"
            "Node.js and Python are bundled; no separate installation is needed.\n"
            "To use an existing ledger, copy its data folder beside the exe.\n\n"
            "请先完整解压整个文件夹，再双击 Stock Ledger.exe。\n"
            "无需安装 Node.js 或 Python。使用原账本时，将原 data 文件夹复制到 exe 旁。\n"
        ).encode("utf-8"))
    with zipfile.ZipFile(destination) as package:
        invalid = package.testzip()
        if invalid:
            raise RuntimeError(f"Release archive failed CRC validation: {invalid}")
    with destination.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(destination), "bytes": destination.stat().st_size, "sha256": digest}


def main() -> None:
    if sys.platform != "win32":
        sys.exit("Run this script with native Windows Python, not Linux/WSL Python.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-node", action="store_true")
    parser.add_argument("--package", action="store_true", help="Build and smoke-test the Windows executable")
    parser.add_argument("--archive", action="store_true", help="Also save a verified Windows zip in desktop/release")
    parser.add_argument("--require-gpu", action="store_true", help="Fail when hardware GPU compositing is unavailable")
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "desktop/test-results/windows-native")
    options = parser.parse_args()
    if options.archive and not options.package:
        parser.error("--archive requires --package")
    work = options.work_dir or Path(tempfile.mkdtemp(prefix="StockLedgerDesktop-native-"))
    work = work.resolve()
    marker = work / ".stock-ledger-validation"
    if work.exists() and any(work.iterdir()) and not marker.exists():
        raise RuntimeError("Choose an empty scratch directory or a previous Stock Ledger validation directory")
    work.mkdir(parents=True, exist_ok=True)
    marker.touch()
    output = options.output.resolve()
    if output == work or work.is_relative_to(output) or output.is_relative_to(work):
        raise RuntimeError("The report directory must be separate from the scratch directory")
    output.mkdir(parents=True, exist_ok=True)
    logs = work / "logs"
    if logs.exists():
        shutil.rmtree(logs)
    logs.mkdir(exist_ok=True)
    report = {"status": "running", "work_directory": str(work), "packaged": options.package,
              "require_gpu": options.require_gpu, "python": sys.version.split()[0]}
    try:
        existing_node = shutil.which("node")
        node = Path(existing_node) if existing_node else portable_node(work) if options.bootstrap_node else None
        if node is None:
            raise RuntimeError("Install Node.js 24 LTS or pass --bootstrap-node")
        node = node.resolve()
        npm = node.parent / "node_modules/npm/bin/npm-cli.js"
        if not npm.exists():
            raise RuntimeError(f"npm is missing beside {node}")
        report["node"] = subprocess.check_output([str(node), "--version"], text=True).strip()
        project = work / "project"
        project.mkdir(exist_ok=True)
        for name in ("desktop_backend.py", "ledger.py", "storage.py", "finance.py", "quotes.py",
                     "i18n.py", "csv_export.py", "icon.ico", "run_desktop.bat", "test_ledger.py", "test_desktop_backend.py"):
            shutil.copy2(ROOT / name, project / name)
        shutil.copytree(ROOT / "desktop", project / "desktop", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("node_modules", "out", "release", "resources", "test-results",
                                                     "playwright-report", ".python-build", "__pycache__"))
        previous_tests = project / "desktop/test-results"
        if previous_tests.exists():
            shutil.rmtree(previous_tests)
        python_folder = work / "python"
        if not (python_folder / "Scripts/python.exe").exists():
            print("[Windows] Creating isolated Python environment", flush=True)
            venv.EnvBuilder(with_pip=True).create(python_folder)
        python = python_folder / "Scripts/python.exe"
        environment = dict(os.environ)
        environment.update({
            "PATH": os.pathsep.join((str(node.parent), str(python.parent), os.environ.get("PATH", ""))),
            "STOCK_LEDGER_PYTHON": str(python), "STOCK_LEDGER_TEST_PYTHON": str(python),
            "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1",
            "PYINSTALLER_CONFIG_DIR": str(work / "pyinstaller-cache"),
            "electron_config_cache": str(work / "electron-cache"),
            "ELECTRON_BUILDER_CACHE": str(work / "builder-cache"),
        })
        for variable in ("ELECTRON_RUN_AS_NODE", "STOCK_LEDGER_DISABLE_GPU", "ELECTRON_RENDERER_URL", "PYTHONPATH"):
            environment.pop(variable, None)
        if options.require_gpu:
            environment["STOCK_LEDGER_REQUIRE_GPU"] = "1"
        else:
            environment.pop("STOCK_LEDGER_REQUIRE_GPU", None)
        desktop = project / "desktop"
        npm_command = [str(node), str(npm)]
        run("Python core tests", [str(python), "test_ledger.py"], project, environment, logs)
        run("Python service tests", [str(python), "-m", "unittest", "-q", "test_desktop_backend"], project, environment, logs)
        run("Install dependencies", npm_command + ["ci", "--cache", str(work / "npm-cache"), "--no-audit", "--no-fund"],
            desktop, environment, logs)
        if options.package:
            run("Install build tools", [str(python), "-m", "pip", "install", "--cache-dir", str(work / "pip-cache"),
                                        "-r", str(desktop / "requirements-build.txt")], desktop, environment, logs)
        run("Build Windows app" if options.package else "Build renderer",
            npm_command + ["run", "package:dir" if options.package else "build"], desktop, environment, logs)
        run("Unit tests", npm_command + ["test"], desktop, environment, logs)
        run("Native window tests", npm_command + ["run", "test:browser"], desktop, environment, logs)
        if options.package:
            run("Packaged executable test", npm_command + ["run", "test:package"], desktop, environment, logs)
            report["executable"] = str(desktop / "release/win-unpacked/Stock Ledger.exe")
            packaged_gpu = desktop / "test-results/packaged-gpu.json"
            if packaged_gpu.exists():
                report["packaged_runtime"] = json.loads(packaged_gpu.read_text("utf-8"))
            if options.archive:
                print("[Windows] Creating verified release archive", flush=True)
                arch = "arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "x64"
                report["archive"] = archive_bundle(Path(report["executable"]),
                                                    ROOT / f"desktop/release/StockLedger-Windows-{arch}.zip")
        report["status"] = "passed"
    except Exception as error:
        report["status"], report["error"] = "failed", str(error)
        raise
    finally:
        tests = work / "project/desktop/test-results"
        if tests.exists():
            shutil.copytree(tests, output / "tests", dirs_exist_ok=True)
            metrics = next(tests.glob("**/frame-timing.json"), None)
            if metrics:
                report["animation"] = json.loads(metrics.read_text("utf-8"))
        shutil.copytree(logs, output / "logs", dirs_exist_ok=True)
        (output / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
