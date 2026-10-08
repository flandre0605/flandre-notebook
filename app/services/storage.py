"""Startup orchestration; database migrations remain inside the database layer."""
from app.database import store
from app.paths import prepare_data_directory
from app.services.backup import validate_data_directory


def initialize_storage() -> str:
    notice = prepare_data_directory(validate_data_directory, target=store.DATA_DIR)
    store.initialize()
    return notice


def use_directory(directory):
    """Called on the UI thread only after the previous workspace is idle and detached."""
    import os
    from pathlib import Path
    from app import paths
    from app.services import attachments, backup
    directory = Path(directory).resolve()
    paths.DATA_DIR = store.DATA_DIR = directory
    store.DATABASE_PATH = directory / 'questions.db'
    attachments.ATTACHMENTS_DIR = backup.ATTACHMENTS_DIR = directory / 'attachments'
    os.environ['FLANDRE_DATA_DIR'] = str(directory)
