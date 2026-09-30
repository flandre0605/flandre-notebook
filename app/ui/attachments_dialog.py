import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app.database import store
from app.services import attachments


class AttachmentsDialog(QDialog):
    def __init__(self, question_id: int, parent=None):
        super().__init__(parent)
        self.question_id = question_id
        self.setWindowTitle("题目图片")
        self.resize(900, 560)

        self.files = QListWidget()
        self.files.setMinimumWidth(220)
        self.files.currentItemChanged.connect(self.show_preview)
        self.preview = QLabel("选择图片预览")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(420, 360)
        self.preview.setStyleSheet(
            "background: #f8f9fc; border: 1px solid #e7ebf2; border-radius: 10px;"
            " color: #8490a1;"
        )

        self.add_button = QPushButton("添加图片")
        self.remove_button = QPushButton("移除图片")
        self.close_button = QPushButton("关闭")
        self.add_button.clicked.connect(self.add_images)
        self.remove_button.clicked.connect(self.remove_image)
        self.close_button.clicked.connect(self.accept)

        left = QVBoxLayout()
        left.addWidget(self.files, 1)
        left.addWidget(self.add_button)
        left.addWidget(self.remove_button)
        right = QVBoxLayout()
        right.addWidget(self.preview, 1)
        right.addWidget(self.close_button, alignment=Qt.AlignmentFlag.AlignRight)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        layout.addLayout(left)
        layout.addLayout(right, 1)
        self.refresh()

    def refresh(self):
        current = self.files.currentItem()
        selected_id = current.data(Qt.ItemDataRole.UserRole)["id"] if current else None
        try:
            rows = store.list_attachments(self.question_id)
        except sqlite3.Error as error:
            QMessageBox.critical(self, "读取失败", f"无法读取图片附件：\n{error}")
            return
        self.files.clear()
        selected_row = 0
        for index, attachment in enumerate(rows):
            item = QListWidgetItem(attachment["original_name"])
            item.setData(
                Qt.ItemDataRole.UserRole,
                {"id": attachment["id"], "path": attachment["relative_path"]},
            )
            self.files.addItem(item)
            if attachment["id"] == selected_id:
                selected_row = index
        if self.files.count():
            self.files.setCurrentRow(selected_row)
        else:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("还没有图片附件")
        self.remove_button.setEnabled(self.files.count() > 0)

    def show_preview(self, item, _previous=None):
        if item is None:
            return
        try:
            path = attachments.attachment_file(
                item.data(Qt.ItemDataRole.UserRole)["path"]
            )
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                self.preview.setPixmap(QPixmap())
                self.preview.setText("图片无法预览")
                return
            self.preview.setText("")
            self.preview.setPixmap(
                pixmap.scaled(
                    self.preview.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        except (OSError, ValueError) as error:
            self.preview.setPixmap(QPixmap())
            self.preview.setText(f"无法读取图片：{error}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.show_preview(self.files.currentItem())

    def add_images(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "选择题目图片",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.webp)",
        )
        errors = []
        for path in paths:
            try:
                attachments.import_image(self.question_id, path)
            except (ValueError, OSError, sqlite3.Error) as error:
                errors.append(f"{path}\n{error}")
        self.refresh()
        if errors:
            QMessageBox.warning(self, "部分图片未导入", "\n\n".join(errors))

    def remove_image(self):
        item = self.files.currentItem()
        if item is None:
            return
        answer = QMessageBox.question(self, "移除图片", "从题目中移除这张图片？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            attachments.delete_image(item.data(Qt.ItemDataRole.UserRole)["id"])
        except (ValueError, OSError, sqlite3.Error) as error:
            QMessageBox.critical(self, "移除失败", str(error))
            return
        self.refresh()
