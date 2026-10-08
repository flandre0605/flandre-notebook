"""Build a standalone folder, portable ZIP and optionally an Inno Setup installer."""
import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.4.0-preview.5"


def build(compiler=None):
    if sys.platform != "win32":
        raise RuntimeError("Windows 包需要在 Windows 上构建。")
    output = ROOT / "dist" / VERSION
    # A development tool's PATH can shadow Windows DLLs (notably the ICU facade used by Qt).
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    windows = Path(os.environ.get("SystemRoot", "C:/Windows"))
    env["PATH"] = os.pathsep.join(str(path) for path in (
        Path(sys.executable).parent, Path(sys.base_prefix), windows / "System32", windows))
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--distpath", str(output), "--workpath", str(ROOT / "build"),
                    str(ROOT / "packaging" / "flandre.spec")], cwd=ROOT, env=env, check=True)
    bundle = output / "FlandreNotebook"
    shutil.copy2(ROOT / "packaging" / "使用说明.txt", bundle)
    shutil.copy2(ROOT / "packaging" / "THIRD_PARTY_NOTICES.md", bundle)
    shutil.copytree(ROOT / "packaging" / "licenses", bundle / "licenses", dirs_exist_ok=True)
    shutil.copy2(Path(sys.base_prefix) / "LICENSE.txt", bundle / "licenses" / "PYTHON.txt")
    from ziafont import Font
    fonts = []
    for distribution, file in (("ziamath", "STIXTwoMath-Regular.ttf"), ("ziafont", "DejaVuSans.ttf")):
        location = Path(importlib.util.find_spec(distribution).origin).parent / "fonts" / file
        names = Font(location).info.names
        fonts.append(f"{names.family}\n{names.copyright}\n{names.trademark}\n{names.license}\n{names.LicenseURL}")
    (bundle / "licenses" / "FONTS.txt").write_text("\n\n".join(fonts), encoding="utf-8")
    manifest = dict(version=VERSION, python=sys.version, platform=sys.platform,
                    dependencies={item.metadata['Name']: item.version for item in importlib.metadata.distributions()})
    source_hash = hashlib.sha256()
    for file in sorted([ROOT / "main.py", *(ROOT / "app").rglob("*.py")]):
        source_hash.update(file.relative_to(ROOT).as_posix().encode() + b"\0" + file.read_bytes())
    manifest["source_sha256"] = source_hash.hexdigest()
    (bundle / "build-info.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    portable = output / f"FlandreNotebook-{VERSION}-portable-x64.zip"
    with zipfile.ZipFile(portable, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(bundle.rglob("*")):
            if file.is_file():
                archive.write(file, file.relative_to(output).as_posix())
    artifacts = [portable]
    if compiler:
        subprocess.run([str(compiler), f"/DAppVersion={VERSION}", f"/DBundleDir={bundle}", f"/O{output}",
                        str(ROOT / "packaging" / "installer.iss")], cwd=ROOT, check=True)
        artifacts.append(output / f"FlandreNotebook-{VERSION}-setup-x64.exe")
    hashes = []
    for file in artifacts:
        with file.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else hashlib.sha256(stream.read()).hexdigest()
        hashes.append(f"{digest}  {file.name}")
        print(f"Built: {file} ({file.stat().st_size / 1024 / 1024:.1f} MiB)")
    (output / "SHA256SUMS.txt").write_text("\n".join(hashes) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--iscc", type=Path, help="Inno Setup ISCC.exe path; omit for portable build only")
    args = parser.parse_args()
    build(args.iscc)
