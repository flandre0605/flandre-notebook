"""Optional local DeeperSeeker bridge; account login stays in its dashboard."""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import time
from threading import Event
import urllib.error
import urllib.request

from app.services import credentials
from app.paths import DATA_DIR, LEGACY_DATA_DIR, PROJECT_ROOT
from PySide6.QtCore import QSettings

BUNDLED_SERVICE = PROJECT_ROOT / "services/deepseek-web/FlandreDeepSeek.exe"


def _bridge_directory():
    saved = str(QSettings("FlandreNotebook", "LocalServices").value("deepseek/bridge", "") or "")
    path = Path(saved)
    if saved and path.is_absolute() and ((path / "app.py").is_file() and (path / ".venv/Scripts/python.exe").is_file()
                                         or BUNDLED_SERVICE.is_file() and path.is_dir()):
        return path
    legacy = LEGACY_DATA_DIR / "tools" / "deeperseeker"
    return legacy if (legacy / "app.py").is_file() else DATA_DIR / "tools" / "deeperseeker"


# Virtual environments cannot be moved; remember their location across app versions and accounts.
BRIDGE = _bridge_directory()
REVISION = "7e550f552b5b31429dcf5213394ca3e74154708f"
ORIGIN = "http://127.0.0.1:4000"
KEY_REF = "deepseek-web-local"
_process = None
_shutdown = Event()


def _remember_bridge():
    settings = QSettings("FlandreNotebook", "LocalServices")
    settings.setValue("deepseek/bridge", str(BRIDGE.resolve()))
    settings.sync()
    if settings.status() != QSettings.Status.NoError:
        raise RuntimeError("无法保存网页版服务位置，请检查当前用户的设置写入权限。")


def local_key():
    if not credentials.has_api_key(KEY_REF):
        credentials.save_api_key(KEY_REF, secrets.token_urlsafe(32))
    return credentials.get_api_key(KEY_REF)


def _models(key):
    request = urllib.request.Request(f"{ORIGIN}/v1/models", headers={"Authorization": f"Bearer {key}"})
    # Local requests must not inherit a system HTTP proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=2) as response:
        data = json.load(response).get("data", [])
    if not any(item.get("id") == "v4.1flash" for item in data if isinstance(item, dict)):
        raise RuntimeError("4000 端口上的服务不是预期的 DeeperSeeker。")


def start():
    global _process
    if _shutdown.is_set():
        raise RuntimeError("程序正在退出，已取消服务启动。")
    if BUNDLED_SERVICE.is_file():
        command = [str(BUNDLED_SERVICE)]
        BRIDGE.mkdir(parents=True, exist_ok=True)
    else:
        python = BRIDGE / ".venv" / "Scripts" / "python.exe"
        if not python.exists() or not (BRIDGE / "app.py").exists():
            raise RuntimeError("缺少内置网页版服务，请使用完整解压的新版程序；源码运行请按接入文档准备开发环境。")
        revision = subprocess.check_output(["git", "-C", str(BRIDGE), "rev-parse", "HEAD"], text=True).strip()
        if revision != REVISION:
            raise RuntimeError("网页版服务版本与已审查版本不一致，请按接入文档重新检查。")
        command = [str(python), str(BRIDGE / "app.py")]
    _remember_bridge()
    key = local_key()
    with socket.socket() as probe:
        occupied = probe.connect_ex(("127.0.0.1", 4000)) == 0
    if occupied:
        try:
            _models(key)
        except Exception:
            raise RuntimeError("4000 端口已被其他服务占用，或本地服务密钥不匹配。") from None
        return key
    env = os.environ.copy()
    env.update(HOST="127.0.0.1", PORT="4000", DEEPSEEKER_API_KEY=key,
               DEEPSEEKER_ADMIN_USER="notebook", DEEPSEEKER_ADMIN_PASSWORD=key,
               DB_PATH=str(BRIDGE / "deeperseeker.db"),
               DEEPSEEKER_UPSTREAM_BASE="https://chat.deepseek.com",
               DEEPSEEKER_UPSTREAM_FALLBACK="", DEEPSEEKER_MAX_UPSTREAM_ATTEMPTS="1",
               DEEPSEEKER_TOKEN_CONCURRENCY="1", TRUSTED_PROXIES="",
               PYTHONIOENCODING="utf-8")
    with (BRIDGE / "service.log").open("ab") as log:
        _process = subprocess.Popen(command, cwd=BRIDGE,
                                    env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    for _ in range(150):
        if _shutdown.is_set() or _process is None or _process.poll() is not None:
            break
        try:
            _models(key)
            return key
        except (OSError, ValueError, RuntimeError):
            time.sleep(0.2)
    stop()
    raise RuntimeError(f"网页版服务启动失败，请查看 {BRIDGE / 'service.log'}。")


def shutdown():
    _shutdown.set()
    stop()


def stop():
    global _process
    process, _process = _process, None
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def install():
    """Explicit one-time setup; never runs during normal notebook startup."""
    import venv
    if not BRIDGE.exists():
        subprocess.run(["git", "clone", "https://github.com/AmanCode22/deeperseeker.git", str(BRIDGE)], check=True)
        subprocess.run(["git", "-C", str(BRIDGE), "checkout", "--detach", REVISION], check=True)
    revision = subprocess.check_output(["git", "-C", str(BRIDGE), "rev-parse", "HEAD"], text=True).strip()
    if revision != REVISION:
        raise RuntimeError("已有目录版本不同，未覆盖；请先检查该目录。")
    python = BRIDGE / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(BRIDGE / ".venv")
    # Playwright is an optional upstream fallback; no browser package is installed.
    subprocess.run([str(python), "-m", "pip", "install", "wasmtime", "aiohttp", "uvicorn", "fastapi",
                    "python-multipart", "jinja2", "deepseek-tokenizer", "python-dotenv"], check=True)
    _remember_bridge()


if __name__ == "__main__":
    install()
