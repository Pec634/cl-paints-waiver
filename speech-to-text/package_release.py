"""Create a shareable ZIP containing only application files, never user data."""
from pathlib import Path
import shutil
import zipfile


def main():
    base = Path(__file__).resolve().parent
    folder = base / "dist" / "LocalSpeechToText"
    executable = folder / "LocalSpeechToText.exe"
    if not executable.is_file() or not (folder / "_internal").is_dir():
        raise RuntimeError("Build LocalSpeechToText.spec before packaging")
    shutil.copyfile(base / "PORTABLE-README.txt", folder / "README.txt")
    archive = base / "dist" / "LocalSpeechToText-Windows.zip"
    files = [executable, folder / "README.txt"]
    files += sorted(p for p in (folder / "_internal").rglob("*") if p.is_file())
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for path in files:
            output.write(path, path.relative_to(folder.parent))
    with zipfile.ZipFile(archive) as output:
        bad = output.testzip()
        if bad:
            raise RuntimeError(f"ZIP integrity check failed: {bad}")
    print(f"Ready to share: {archive} ({archive.stat().st_size / 1_000_000:.0f} MB)")


if __name__ == "__main__":
    main()
