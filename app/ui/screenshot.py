import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import QApplication, QWidget


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

    def __init__(self, window, callback, shortcut="Ctrl+Alt+S"):
        super().__init__()
        self.window = window
        self.callback = callback
        self.shortcut = QKeySequence(shortcut)
        self.app = QApplication.instance()
        self.user32 = None
        self.registered = False
        self.fallback = None
        self.native_modifiers, self.native_key = self._native_combination(self.shortcut)
        if sys.platform == "win32":
            self.user32 = ctypes.WinDLL("user32", use_last_error=True)
            self.user32.RegisterHotKey.argtypes = (
                wintypes.HWND, wintypes.INT, wintypes.UINT, wintypes.UINT
            )
            self.user32.RegisterHotKey.restype = wintypes.BOOL
            self.user32.UnregisterHotKey.argtypes = (wintypes.HWND, wintypes.INT)
            self.user32.UnregisterHotKey.restype = wintypes.BOOL
            if self.native_key is not None:
                self.registered = bool(self.user32.RegisterHotKey(
                    wintypes.HWND(int(window.winId())),
                    self.HOTKEY_ID,
                    self.native_modifiers | self.MOD_NOREPEAT,
                    self.native_key,
                ))
            if self.registered:
                self.app.installNativeEventFilter(self)
        if not self.registered:
            if not self.shortcut.isEmpty():
                self.fallback = QShortcut(self.shortcut, window)
                self.fallback.setContext(Qt.ShortcutContext.ApplicationShortcut)
                self.fallback.activated.connect(callback)

    @staticmethod
    def _native_combination(sequence):
        if sequence.count() != 1:
            return 0, None
        combination = sequence[0]
        modifiers = combination.keyboardModifiers()
        native_modifiers = 0
        for qt_modifier, win_modifier in (
            (Qt.KeyboardModifier.ControlModifier, GlobalScreenshotHotkey.MOD_CONTROL),
            (Qt.KeyboardModifier.AltModifier, GlobalScreenshotHotkey.MOD_ALT),
            (Qt.KeyboardModifier.ShiftModifier, 0x0004),
            (Qt.KeyboardModifier.MetaModifier, 0x0008),
        ):
            if modifiers & qt_modifier:
                native_modifiers |= win_modifier
        if not native_modifiers:
            return 0, None

        key = int(combination.key())
        if 0x30 <= key <= 0x39 or 0x41 <= key <= 0x5A:
            return native_modifiers, key
        if int(Qt.Key.Key_F1) <= key <= int(Qt.Key.Key_F24):
            return native_modifiers, 0x70 + key - int(Qt.Key.Key_F1)
        special_keys = {
            int(Qt.Key.Key_Space): 0x20,
            int(Qt.Key.Key_Tab): 0x09,
            int(Qt.Key.Key_Return): 0x0D,
            int(Qt.Key.Key_Enter): 0x0D,
            int(Qt.Key.Key_Escape): 0x1B,
            int(Qt.Key.Key_Backspace): 0x08,
            int(Qt.Key.Key_Delete): 0x2E,
            int(Qt.Key.Key_Insert): 0x2D,
            int(Qt.Key.Key_Home): 0x24,
            int(Qt.Key.Key_End): 0x23,
            int(Qt.Key.Key_PageUp): 0x21,
            int(Qt.Key.Key_PageDown): 0x22,
            int(Qt.Key.Key_Left): 0x25,
            int(Qt.Key.Key_Up): 0x26,
            int(Qt.Key.Key_Right): 0x27,
            int(Qt.Key.Key_Down): 0x28,
        }
        return native_modifiers, special_keys.get(key)

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
        if self.fallback is not None:
            self.fallback.setEnabled(False)
            self.fallback.deleteLater()
            self.fallback = None
