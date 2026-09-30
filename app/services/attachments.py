import mimetypes
import shutil
from pathlib import Path
from uuid import uuid4

from PySide6.QtGui import QImageReader

from app.database import store


SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_IMAGE_BYTES = 20 * 1024 * 1024
ATTACHMENTS_DIR = store.DATA_DIR / "attachments"


def validate_image(source: str | Path) -> Path:
    source = Path(source)
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError("仅支持 PNG、JPG、JPEG 和 WEBP 图片。")
    if not source.is_file() or source.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError("图片不存在或超过 20 MB。")
    if not QImageReader(str(source)).canRead():
        raise ValueError("文件内容不是可读取的图片。")
    return source


def import_image(question_id: int, source: str | Path) -> int:
    source = validate_image(source)
    suffix = source.suffix.lower()

    ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid4().hex}{suffix}"
    destination = ATTACHMENTS_DIR / stored_name
    shutil.copyfile(source, destination)
    try:
        mime_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        return store.add_attachment(
            question_id,
            f"attachments/{stored_name}",
            source.name,
            mime_type,
        )
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def attachment_file(relative_path: str) -> Path:
    root = ATTACHMENTS_DIR.resolve()
    path = (store.DATA_DIR / relative_path).resolve()
    if not path.is_relative_to(root):
        raise ValueError("附件路径无效。")
    return path


def delete_image(attachment_id: int) -> None:
    relative_path = store.delete_attachment(attachment_id)
    if relative_path is None:
        return
    attachment_file(relative_path).unlink(missing_ok=True)


def delete_question_images(question_id: int) -> list[str]:
    rows = store.list_attachments(question_id)
    store.delete_question(question_id)
    failures = []
    for row in rows:
        try:
            attachment_file(row["relative_path"]).unlink(missing_ok=True)
        except (OSError, ValueError) as error:
            failures.append(f"{row['original_name']}: {error}")
    return failures
