"""Build a single-file desktop executable with PyInstaller.

User data is deliberately not bundled.  The application stores its SQLite
database in the platform data directory so replacing the executable does not
replace prompts, settings, or remembered placeholder values.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    """Run PyInstaller with platform-neutral options."""

    root = Path(__file__).resolve().parent
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller 未安装，请先执行: python -m pip install -r requirements-build.txt")
        return 1
    result = subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
        "--windowed", "--name", "PromptManager", str(root / "launcher.py"),
    ], cwd=root, check=False)
    if result.returncode == 0:
        print(f"构建完成，输出目录：{root / 'dist'}")
        print("用户数据库不会打包进 exe；升级时会继续使用系统数据目录中的 prompts.sqlite3")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
