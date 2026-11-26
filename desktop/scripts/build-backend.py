"""Build on the target OS; the service needs Python's stdlib, not PyQt6."""
import importlib.util
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
if importlib.util.find_spec("PyInstaller") is None:
    sys.exit("Install the packaging dependency first: python -m pip install pyinstaller")
subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
                "--name", "stock-ledger-service", "--distpath", str(root / "desktop/resources"),
                "--workpath", str(root / "desktop/.python-build"),
                "--specpath", str(root / "desktop/.python-build"), str(root / "desktop_backend.py")],
               cwd=root, check=True)
