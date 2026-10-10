from pathlib import Path
import os
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

root = Path(SPECPATH).parent
assets = root / "assets"
data = [(str(assets / name), "assets") for name in (
    "flandre_icon.ico", "flandre_icon.png", "flandre_pet_chibi.png", "pet_walk_user.png", "pet_motion.png", "question_template.csv",
    "vocabulary_template.csv", "vocabulary_template.txt")]
data += [(str(assets / "ui"), "assets/ui")]
data += [(str(assets / "pet_expressions"), "assets/pet_expressions")]
data += [(str(root / "cloud" / "sql"), "cloud/sql")]
data += [(str(root / "build/bundled-deepseek/FlandreDeepSeek"), "services/deepseek-web")]
data += collect_data_files("ziamath") + collect_data_files("ziafont") + collect_data_files("latex2mathml")
for distribution in ("keyring", "PySide6", "PySide6_Essentials", "PySide6_Addons", "ziamath"):
    data += copy_metadata(distribution, recursive=True)

analysis = Analysis([str(root / "main.py")], pathex=[str(root)], datas=data,
                    hiddenimports=["keyring.backends.Windows", "keyring.backends.chainer", "keyring.backends.fail"],
                    excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
                              "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets"],
                    binaries=[], hookspath=[], runtime_hooks=[], noarchive=False)
archive = PYZ(analysis.pure)
executable = EXE(archive, analysis.scripts, [], exclude_binaries=True, name="FlandreNotebook",
                 debug=False, strip=False, upx=False, console=bool(os.environ.get("FLANDRE_BUILD_CONSOLE")),
                 icon=str(assets / "flandre_icon.ico"))
bundle = COLLECT(executable, analysis.binaries, analysis.datas, strip=False, upx=False,
                 name="FlandreNotebook")
