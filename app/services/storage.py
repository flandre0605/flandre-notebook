"""Startup orchestration; database migrations remain inside the database layer."""
from app.database import store
from app.paths import prepare_data_directory
from app.services.backup import validate_data_directory


def initialize_storage() -> str:
    notice = prepare_data_directory(validate_data_directory, target=store.DATA_DIR)
    store.initialize()
    return notice
