"""Shared model choices for settings, image recognition and vocabulary."""
from PySide6.QtCore import QSettings, QSignalBlocker
from app.database import store


def fill_model_choices(combo, purpose, default_picker=False, use_default=False):
    key = f"default_models/{purpose}"
    preferred = QSettings().value(key, "")
    selected = preferred if default_picker or use_default else combo.currentData()
    profiles = [row for row in store.list_profiles(enabled_only=True)
                if purpose != "vision" or row["vision_enabled"]]
    with QSignalBlocker(combo):
        combo.clear()
        if default_picker:
            combo.addItem("自动选择可用配置", "")
        for row in profiles:
            combo.addItem(f"{row['name']} · {row['model_id']}", row["id"])
        if not combo.count():
            combo.addItem("请先添加并启用可用的模型配置", None)
        index = combo.findData(selected)
        if index < 0 and not default_picker:
            index = combo.findData(preferred)
        combo.setCurrentIndex(max(0, index))
    return profiles
