"""Run the actual executable in a temporary workspace without Python or model access."""
import argparse
from contextlib import nullcontext
import json
import os
from pathlib import Path
import subprocess
import tempfile


def check(executable, workspace=None):
    executable = Path(executable).resolve()
    context = nullcontext(workspace) if workspace is not None else tempfile.TemporaryDirectory(prefix="flandre-package-check-")
    with context as directory:
        root = Path(directory).resolve()
        root.mkdir(parents=True, exist_ok=True)
        report = root / "report.json"
        env = os.environ.copy()
        env.update(FLANDRE_DATA_DIR=str(root / "learning-data"),
                   QT_QPA_PLATFORM=env.get("QT_QPA_PLATFORM", "offscreen"))
        env.pop("PYTHONPATH", None)
        # Launch from outside the source checkout. The executable must find its own resources.
        result = subprocess.run([str(executable), "--verify-package", str(report)], cwd=root, env=env,
                                timeout=60, creationflags=subprocess.CREATE_NO_WINDOW,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert report.is_file(), f"No runtime report; exit code {result.returncode}\n{result.stderr.decode('utf-8', errors='replace')}"
        data = json.loads(report.read_text(encoding="utf-8"))
        assert result.returncode == 0 and data["ok"] and data["frozen"], data
        print(json.dumps(data, ensure_ascii=True))
        return root / "learning-data"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    check(parser.parse_args().executable)
