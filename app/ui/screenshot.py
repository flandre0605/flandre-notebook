import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QShortcut, QWidget


class ScreenshotOverlay(QWidget):
    captured = Signal(QPixmap)
    cancelled = Signal()

    def __init__(self, screen, screenshot):
        super().__init__(None)
        self.screenshot = screenshot
        self.origin = None
        self.selection = QRect()
        self.setGeometry(screen.geometry())
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.screenshot)
        painter.fillRect(self.rect(), QColor(17, 27, 45, 125))
        if not self.selection.isNull():
            scale_x = self.screenshot.width() / max(1, self.width())
            scale_y = self.screenshot.height() / max(1, self.height())
            source = QRect(
                round(self.selection.x() * scale_x),
                round(self.selection.y() * scale_y),
                round(self.selection.width() * scale_x),
                round(self.selection.height() * scale_y),
            )
            painter.drawPixmap(self.selection, self.screenshot.copy(source))
            painter.setPen(QPen(QColor("#ffffff"), 1))
            painter.drawRect(self.selection.adjusted(0, 0, -1, -1))
            painter.setPen(QPen(QColor("#4c78ee"), 2))
            painter.drawRect(self.selection.adjusted(1, 1, -2, -2))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(31, 45, 67, 230))
        hint = QRect(0, 24, self.width(), 44)
        painter.drawRoundedRect(QRect(self.width() // 2 - 170, 24, 340, 40), 10, 10)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(hint, Qt.AlignmentFlag.AlignCenter, "拖动框选题目区域   ·   Esc 取消")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.origin = event.position().toPoint()
            self.selection = QRect(self.origin, self.origin)
            self.update()

    def mouseMoveEvent(self, event):
        if self.origin is not None:
            self.selection = QRect(self.origin, event.position().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.origin is None:
            return
        self.selection = QRect(self.origin, event.position().toPoint()).normalized()
        self.origin = None
        if self.selection.width() < 8 or self.selection.height() < 8:
            self.update()
            return
        scale_x = self.screenshot.width() / max(1, self.width())
        scale_y = self.screenshot.height() / max(1, self.height())
        source = QRect(
            round(self.selection.x() * scale_x),
            round(self.selection.y() * scale_y),
            round(self.selection.width() * scale_x),
            round(self.selection.height() * scale_y),
        ).intersected(self.screenshot.rect())
        if not source.isEmpty():
            self.captured.emit(self.screenshot.copy(source))
            self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()
            return
        super().keyPressEvent(event)


class GlobalScreenshotHotkey(QAbstractNativeEventFilter):
    HOTKEY_ID = 0x4A11
    MOD_CONTROL = 0x0002
    MOD_ALT = 0x0001
    MOD_NOREPEAT = 0x4000
    WM_HOTKEY = 0x0312

    def __init__(self, window, callback):
        super().__init__()
        self.window = window
        self.callback = callback
        self.app = QApplication.instance()
        self.user32 = None
        self.registered = False
        self.fallback = None
        if sys.platform == "win32":
            self.user32 = ctypes.WinDLL("user32", use_last_error=True)
            self.user32.RegisterHotKey.argtypes = (
                wintypes.HWND, wintypes.INT, wintypes.UINT, wintypes.UINT
            )
            self.user32.RegisterHotKey.restype = wintypes.BOOL
            self.user32.UnregisterHotKey.argtypes = (wintypes.HWND, wintypes.INT)
            self.user32.UnregisterHotKey.restype = wintypes.BOOL
            self.registered = bool(
                self.user32.RegisterHotKey(
                    wintypes.HWND(int(window.winId())),
                    self.HOTKEY_ID,
                    self.MOD_CONTROL | self.MOD_ALT | self.MOD_NOREPEAT,
                    ord("S"),
                )
            )
            if self.registered:
                self.app.installNativeEventFilter(self)
        if not self.registered:
            self.fallback = QShortcut(QKeySequence("Ctrl+Alt+S"), window)
            self.fallback.setContext(Qt.ShortcutContext.ApplicationShortcut)
            self.fallback.activated.connect(callback)

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) == b"windows_generic_MSG":
            native_message = ctypes.cast(
                int(message), ctypes.POINTER(wintypes.MSG)
            ).contents
            if native_message.message == self.WM_HOTKEY and native_message.wParam == self.HOTKEY_ID:
                QTimer.singleShot(0, self.callback)
                return True, 0
        return False, 0

    def close(self):
        if self.registered:
            self.app.removeNativeEventFilter(self)
            self.user32.UnregisterHotKey(
                wintypes.HWND(int(self.window.winId())), self.HOTKEY_ID
            )
            self.registered = False
