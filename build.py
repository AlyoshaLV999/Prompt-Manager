"""Build a single-file desktop executable with PyInstaller.

User data is deliberately not bundled. The application stores its SQLite
database in the platform data directory so replacing the executable does not
replace prompts, settings, or remembered placeholder values.
"""

from __future__ import annotations

import logging
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

LOGGER = logging.getLogger("prompt_manager.build")
_MAC_ICON_CHUNKS: tuple[tuple[str, int], ...] = (
    ("icp4", 16),
    ("icp5", 32),
    ("icp6", 64),
    ("ic07", 128),
    ("ic08", 256),
    ("ic09", 512),
    ("ic10", 1024),
)
_ICO_SIZES: tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256)


def _png_bytes(size: int) -> bytes:
    """Render the logo as PNG bytes without adding an image dependency."""

    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from prompt_manager.icon import render_logo

    image = render_logo(size)
    output = QByteArray()
    buffer = QBuffer(output)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(f"Could not open an in-memory buffer for {size}px icon")
    try:
        if not image.save(buffer, "PNG"):
            raise OSError(f"Qt could not encode the {size}px icon as PNG")
    finally:
        buffer.close()
    return bytes(output)


def _write_ico(path: Path) -> None:
    """Write a Windows ICO containing PNG-compressed resolutions."""

    entries = [(size, _png_bytes(size)) for size in _ICO_SIZES]
    directory_size = 6 + 16 * len(entries)
    offset = directory_size
    header = bytearray(struct.pack("<HHH", 0, 1, len(entries)))
    for size, png_data in entries:
        dimension = 0 if size == 256 else size
        header.extend(
            struct.pack(
                "<BBBBHHII",
                dimension,
                dimension,
                0,  # palette size
                0,  # reserved
                1,  # color planes
                32,  # bits per pixel
                len(png_data),
                offset,
            )
        )
        offset += len(png_data)
    path.write_bytes(bytes(header) + b"".join(data for _, data in entries))


def _write_icns(path: Path) -> None:
    """Write a modern PNG-backed macOS ICNS container."""

    chunks: list[bytes] = []
    for chunk_type, size in _MAC_ICON_CHUNKS:
        png_data = _png_bytes(size)
        chunks.append(chunk_type.encode("ascii") + struct.pack(">I", len(png_data) + 8) + png_data)
    body = b"".join(chunks)
    path.write_bytes(b"icns" + struct.pack(">I", len(body) + 8) + body)


def generate_build_icon(directory: Path, platform: str = sys.platform) -> Path | None:
    """Generate a temporary platform icon and return its path.

    Windows receives an ICO and macOS receives an ICNS. Linux desktop launchers
    use the Qt runtime icon; ELF executables have no portable embedded app-icon
    resource format understood by PyInstaller.

    :param directory: Temporary directory in which to create the icon.
    :param platform: Platform identifier, primarily exposed for testing.
    :return: Generated icon path, or ``None`` where executable icons are not
        portable.
    :raises OSError: If the icon cannot be encoded or written.
    """

    if platform == "win32":
        icon_path = directory / "prompt-manager.ico"
        _write_ico(icon_path)
    elif platform == "darwin":
        icon_path = directory / "prompt-manager.icns"
        _write_icns(icon_path)
    else:
        LOGGER.info("Linux executable icons are not portable; Qt will set the window icon")
        return None

    LOGGER.info("Generated %s application icon at %s", platform, icon_path)
    return icon_path


def main() -> int:
    """Run PyInstaller with the project's existing single-file options."""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    root = Path(__file__).resolve().parent
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        LOGGER.error("PyInstaller is not installed; install it with: python -m pip install pyinstaller")
        return 1

    try:
        with tempfile.TemporaryDirectory(prefix="prompt-manager-build-") as temporary_directory:
            icon_path = generate_build_icon(Path(temporary_directory))
            command = [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--onefile",
                "--windowed",
                "--name",
                "PromptManager",
            ]
            if icon_path is not None:
                command.extend(("--icon", str(icon_path)))
            command.append(str(root / "launcher.py"))

            LOGGER.info("Starting PyInstaller: %s", " ".join(command))
            result = subprocess.run(command, cwd=root, check=False)
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        LOGGER.exception("Build failed while generating the icon or running PyInstaller: %s", exc)
        return 1

    if result.returncode != 0:
        LOGGER.error("PyInstaller failed with exit code %d", result.returncode)
        return result.returncode

    LOGGER.info("Build completed successfully; output directory: %s", root / "dist")
    LOGGER.info("User database remains in the platform data directory and is not bundled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
