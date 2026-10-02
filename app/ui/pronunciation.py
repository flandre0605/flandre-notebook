import sys

from PySide6.QtCore import QLocale, QObject, Signal

try:
    from PySide6.QtTextToSpeech import QTextToSpeech
except ImportError:
    QTextToSpeech = None


class Pronunciation(QObject):
    status_changed = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.engine = None
        self.voices = []
        self.status = "当前环境没有可用的系统英语语音。"
        if QTextToSpeech is None:
            return
        engines = [name for name in QTextToSpeech.availableEngines() if name != "mock"]
        if not engines:
            return
        name = "sapi" if sys.platform == "win32" and "sapi" in engines else engines[0]
        self.engine = QTextToSpeech(name, self)
        for locale in self.engine.availableLocales():
            if locale.language() == QLocale.Language.English:
                self.engine.setLocale(locale)
                self.voices.extend(voice for voice in self.engine.availableVoices()
                                   if voice.locale().language() == QLocale.Language.English)
        if self.voices:
            self.engine.setVoice(self.voices[0])
            self.status = "系统英语发音 · 离线可用"
        self.engine.stateChanged.connect(self._state_changed)
        self.engine.errorOccurred.connect(lambda _error, message: self._status(f"发音不可用：{message}"))

    def _status(self, text):
        self.status = text
        self.status_changed.emit(text)

    def _state_changed(self, state):
        if state == QTextToSpeech.State.Speaking:
            self._status("正在朗读…")
        elif state == QTextToSpeech.State.Ready:
            self._status("系统英语发音 · 离线可用" if self.voices else "系统未安装英语语音，请在 Windows 语音设置中添加。")
        elif state == QTextToSpeech.State.Error:
            self._status(f"发音不可用：{self.engine.errorString()}")

    def set_voice(self, index):
        if 0 <= index < len(self.voices):
            self.stop()
            self.engine.setVoice(self.voices[index])

    def say(self, text):
        if not self.engine or not self.voices:
            self._status("系统未安装英语语音，请在 Windows 语音设置中添加。")
            return False
        text = text.strip()
        if not text:
            self._status("请先输入或选择英文单词。")
            return False
        self.engine.stop()
        self.engine.say(text)
        return True

    def stop(self):
        if self.engine:
            self.engine.stop()
