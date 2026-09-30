import keyring
from keyring.core import recommended


SERVICE_NAME = "ai-mistake-notebook"


def _require_secure_backend():
    if not recommended(keyring.get_keyring()):
        raise RuntimeError("系统没有可用的安全凭据存储，请先配置 Windows 凭据管理器。")


def save_api_key(reference: str, value: str) -> None:
    _require_secure_backend()
    keyring.set_password(SERVICE_NAME, reference, value)


def get_api_key(reference: str) -> str:
    _require_secure_backend()
    value = keyring.get_password(SERVICE_NAME, reference)
    if not value:
        raise RuntimeError("此模型配置没有保存 API Key，请编辑配置并重新填写。")
    return value


def has_api_key(reference: str) -> bool:
    _require_secure_backend()
    return bool(keyring.get_password(SERVICE_NAME, reference))


def delete_api_key(reference: str) -> None:
    _require_secure_backend()
    if keyring.get_password(SERVICE_NAME, reference) is not None:
        keyring.delete_password(SERVICE_NAME, reference)
