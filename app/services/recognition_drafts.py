"""Unconfirmed recognition sessions; originals live in the backed-up attachment tree."""
from pathlib import Path
import re
import shutil
from uuid import uuid4

from app.database import store
from app.question_data import validate_question
from app.services import attachments


def image_file(key, state, root=None):
    if not isinstance(key, str) or not re.fullmatch(r"recognition:[0-9a-f]{32}", key):
        raise ValueError("识题草稿编号无效。")
    relative = state.get("image") if isinstance(state, dict) else None
    identity = key.split(":", 1)[1]
    if relative not in {f"attachments/drafts/{identity}{suffix}" for suffix in attachments.SUPPORTED_EXTENSIONS}:
        raise ValueError("识题草稿图片路径无效。")
    root = Path(root) if root is not None else attachments.ATTACHMENTS_DIR
    path = (root / "drafts" / Path(relative).name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("识题草稿图片路径超出存储目录。")
    return path


def validate_state(key, state, root=None):
    path = image_file(key, state, root)
    attachments.validate_image(path)
    drafts = state.get("drafts", [])
    if not isinstance(drafts, list) or len(drafts) > 100:
        raise ValueError("识题草稿列表无效。")
    index = state.get("current_index", 0)
    if type(index) is not int or not 0 <= index < max(1, len(drafts)):
        raise ValueError("识题草稿位置无效。")
    if any(not isinstance(state.get(key, ""), str) or len(state.get(key, "")) > 260 for key in ("profile_id", "source_name")):
        raise ValueError("识题草稿配置信息无效。")
    response = state.get('raw_response', '')
    if not isinstance(response, str) or len(response) > 128000:
        raise ValueError('识题原始响应应为不超过 128000 字的文本。')
    return dict(image=state["image"], drafts=[validate_question(row, draft=True) for row in drafts],
                current_index=index, profile_id=state.get("profile_id", ""), source_name=state.get("source_name", "图片"),
                raw_response=response)


def keys():
    return [key for key in store.workspace_keys("recognition:") if re.fullmatch(r"recognition:[0-9a-f]{32}", key)]


def create(source, profile_id):
    source = attachments.validate_image(source)
    identity = uuid4().hex
    key = f"recognition:{identity}"
    state = dict(image=f"attachments/drafts/{identity}{source.suffix.lower()}", drafts=[],
                 current_index=0, profile_id=profile_id or "", source_name=source.name, raw_response='')
    path = image_file(key, state)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(source, path)
        store.save_workspace(key, state)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return key, state, path


def load(key):
    state = store.load_workspace(key)
    if not state:
        raise ValueError("这份识题草稿已不存在。")
    state = validate_state(key, state)
    return state, image_file(key, state)


def save(key, state):
    store.save_workspace(key, validate_state(key, state))


def discard(key, state):
    path = image_file(key, state)
    store.save_workspace(key, None)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return False
    return True
