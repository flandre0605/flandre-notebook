"""Install and uninstall the actual package in a temporary directory; retain test learning data."""
import argparse
from pathlib import Path
import subprocess
import tempfile
import time
import winreg
from check_windows_package import check


def check_installer(installer):
    key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{5A1BEF50-AEEB-4EE0-9627-475520E730E8}_is1"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key):
            raise RuntimeError("An existing Flandre installation is present; refusing to replace it for a check.")
    except FileNotFoundError:
        pass
    installer = Path(installer).resolve()
    with tempfile.TemporaryDirectory(prefix="flandre-installer-check-") as directory:
        root = Path(directory)
        program = root / "program"
        subprocess.run([str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-",
                        "/NOICONS", "/NOCLOSEAPPLICATIONS", f"/DIR={program}", f"/LOG={root / 'install.log'}"],
                       timeout=60, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        print("Temporary installation succeeded.", flush=True)
        uninstaller = program / "unins000.exe"
        assert uninstaller.is_file()
        try:
            data = check(program / "FlandreNotebook.exe", root)
            saved_database = (data / "questions.db").read_bytes()
        finally:
            subprocess.run([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                            f"/LOG={root / 'uninstall.log'}"], timeout=60, check=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
            for _ in range(100):
                if not program.exists():
                    try:
                        (root / "uninstall.log").unlink(missing_ok=True)
                        break  # Inno's second-phase helper has released its log and removed the program.
                    except PermissionError:
                        pass
                time.sleep(0.1)
            else:
                raise RuntimeError("The uninstall helper did not finish within 10 seconds.")
        assert not (program / "FlandreNotebook.exe").exists()
        assert (data / "questions.db").read_bytes() == saved_database
        assert (data / "attachments").is_dir()
        print("Installer check passed: installed executable works; uninstall preserves learning data.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("installer", type=Path)
    check_installer(parser.parse_args().installer)
