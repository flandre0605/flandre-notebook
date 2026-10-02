"""Temporary-data check; model and speech calls are mocked, with no network or audio."""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import Mock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.database import store, vocabulary
from app.services import vocabulary_translation as translation
from app.services.model_provider import ProviderError
from app.ui.main_window import MainWindow
from app.ui.pronunciation import Pronunciation


class SilentSpeech(QObject):
    status_changed = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.voices = []
        self.status = "检查模式：不播放声音"
        self.speed = 2
        self.spoken = []
        self.stopped = 0

    def say(self, text):
        self.spoken.append(text)

    def stop(self):
        self.stopped += 1

    def set_voice(self, index):
        pass

    def set_speed(self, index):
        self.speed = index


def fails(call, kind=ValueError):
    try:
        call()
    except kind:
        return
    raise AssertionError("Invalid input accepted")


def entries(words):
    return [dict(word=word, meaning="n. 示例释义", phonetic="/wɜːd/", example="A word. 一个单词。") for word in words]


def finished(page):
    for _ in range(300):
        QTest.qWait(10)
        if not page._translation_busy:
            return
    raise AssertionError("Background translation did not finish")


def check(previews=None):
    app = QApplication.instance() or QApplication([])
    for font in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf"):
        QFontDatabase.addApplicationFont(f"C:/Windows/Fonts/{font}")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    profile = dict(name="检查模型", model_id="mock-model", base_url="https://example.com/v1",
                   endpoint_path="/chat/completions", timeout_seconds=5, vision_enabled=False, enabled=True)
    response = json.dumps({"words": entries(["Remember", "keep going"])}, ensure_ascii=False)
    with patch.object(translation, "_request", return_value=f"```json\n{response}\n```") as request:
        assert translation.translate_words(profile, ["Remember", "keep going"])[0]["word"] == "Remember"
        assert request.call_args.kwargs["json_mode"] is True
    with patch.object(translation, "_request", side_effect=[ProviderError("unsupported", retry_without_json_mode=True), response]) as request:
        assert len(translation.translate_words(profile, ["Remember", "keep going"])) == 2
        assert request.call_args.kwargs["json_mode"] is False
    for invalid in ('{"words":[]}', '{"words":[{"word":"extra","meaning":"释义"}]}',
                    '{"words":[{"word":"Remember","meaning":"English only"}]}', "not JSON"):
        with patch.object(translation, "_request", return_value=invalid):
            fails(lambda: translation.translate_words(profile, ["Remember"]), ProviderError)
    with tempfile.TemporaryDirectory() as preferences:
        settings = QSettings(str(Path(preferences) / "settings.ini"), QSettings.Format.IniFormat)
        with patch("app.ui.pronunciation.QTextToSpeech", None), patch("app.ui.pronunciation.QSettings", return_value=settings):
            speech = Pronunciation(None)
            assert not speech.say("word") and not speech.voices and speech.speed == 2
            speech.engine = Mock()
            speech.voices = [object()]
            assert speech.say(" word ")
            speech.engine.say.assert_called_once_with("word")
            assert speech.engine.stop.call_count == 1
            for speed in range(5):
                speech.set_speed(speed)
                speech.engine.setRate.assert_called_with(Pronunciation.RATES[speed])
                assert Pronunciation(None).speed == speed
            speech.set_voice(0)
            speech.engine.setVoice.assert_called_once_with(speech.voices[0])
            speech.engine.setRate.assert_called_with(Pronunciation.RATES[4])
            assert not speech.say(" ")
            speech.set_speed(-1)
            assert speech.speed == 4
            for invalid in ("bad", 99, -2):
                settings.setValue("vocabulary/speech_speed", invalid)
                assert Pronunciation(None).speed == 2
    connection = store._connection
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        database = root / "questions.db"
        store.initialize(database)
        with patch.object(store, "_connection", lambda path=database: connection(path)), patch.object(
            store, "DATABASE_PATH", database
        ), patch.object(store, "DATA_DIR", root), patch("app.ui.main_window.GlobalScreenshotHotkey"), patch(
            "app.ui.vocabulary_page.Pronunciation", SilentSpeech
        ):
            store.save_profile(profile, "mock-profile")
            txt = root / "我的词表.txt"
            txt.write_text("Remember\nkeep going\nhello\t你好\n", encoding="utf-8-sig")
            assert vocabulary.read_word_file(txt)[1]["word"] == "keep going"
            fails(lambda: vocabulary.import_csv(txt))
            assert not vocabulary.list_words()
            csv_file = root / "word-only.csv"
            csv_file.write_text("单词\nhello\n", encoding="gb18030")
            assert vocabulary.read_word_file(csv_file)[0]["meaning"] == ""
            csv_file.write_text("word,word\nhello,hello\n", encoding="utf-8")
            fails(lambda: vocabulary.read_word_file(csv_file))
            window = MainWindow()
            window.resize(1040, 680)
            window.show()
            window.show_vocabulary()
            page = window.vocabulary_page
            assert page.speech_speed.currentText() == "正常" and not page.speech_speed.isEnabled()
            page.speech_speed.setCurrentIndex(0)
            assert page.speech.speed == 0
            assert page.profile.currentData() == "mock-profile"  # text-only profile is usable
            page.edit_word()
            page.word.setText("Remember")
            page.meaning.setPlainText("保留手写释义")
            with patch("app.ui.vocabulary_page.translate_words", side_effect=lambda _p, words: entries(words)):
                page.translate_editor()
                assert not page.word.isEnabled() and not page.save_button.isEnabled()
                finished(page)
            assert page.meaning.toPlainText() == "保留手写释义" and page.phonetic.text()
            assert not vocabulary.list_words()  # no automatic write
            page.save_word()
            word_id = vocabulary.list_words()[0]["id"]
            vocabulary.record_review(word_id, "known")
            previous = dict(vocabulary.get_word(word_id))
            page.import_file(txt)
            assert page.views.currentWidget() is page.import_page
            assert page.import_table.item(0, 1).text() == "保留手写释义"
            page.save_import()
            assert len(vocabulary.list_words()) == 1 and "未导入" in page.import_status.text()
            with patch("app.ui.vocabulary_page.translate_words", side_effect=lambda _p, words: entries(words)) as request:
                page.translate_draft()
                finished(page)
                assert request.call_args.args[1] == ["keep going"]
            assert len(vocabulary.list_words()) == 1
            page.save_import()
            assert len(vocabulary.list_words()) == 3 and dict(vocabulary.get_word(word_id)) == previous
            words = ["word" + chr(97 + index) for index in range(21)]
            txt.write_text("\n".join(words), encoding="utf-8")
            page.import_file(txt)
            with patch("app.ui.vocabulary_page.translate_words", side_effect=[entries(words[:20]), ProviderError("HTTP 502", "details")]) as request:
                page.translate_draft()
                finished(page)
                assert request.call_count == 2 and "失败" in page.import_status.text()
            assert page.import_table.item(19, 1).text() and not page.import_table.item(20, 1).text()
            assert len(vocabulary.list_words()) == 3
            with patch("app.ui.vocabulary_page.translate_words", side_effect=lambda _p, batch: entries(batch)) as request:
                page.translate_draft()
                finished(page)
                assert request.call_args.args[1] == [words[20]]
            if previews:
                previews.mkdir(parents=True, exist_ok=True)
                QTest.qWait(240)
                assert window.width() == 1040 and window.height() == 680
                assert window.grab().save(str(previews / "word-import.png"))
            page.show_library()  # cancel draft without importing
            assert page.resume_import.isVisible()
            page.resume_import.click()
            assert page.views.currentWidget() is page.import_page and page.import_table.item(20, 1).text()
            page.show_library()
            page.import_file(txt)
            with patch("app.ui.vocabulary_page.translate_words", side_effect=lambda _p, batch: entries(batch)) as request:
                page.translate_draft()
                page.cancel_translation()
                finished(page)
                assert request.call_count == 1 and not page.import_table.item(0, 1).text()
            assert len(vocabulary.list_words()) == 3
            page.show_library()
            page.study.begin([vocabulary.get_word(word_id)], "spelling")
            page.views.setCurrentWidget(page.study)
            page.study.auto_speak.setChecked(True)
            page.study.speak()
            assert not page.speech.spoken and not page.study.pronounce.isVisible()
            page.study.answer.setText("remember")
            page.study.reveal()
            assert page.speech.spoken == ["Remember"] and page.study.pronounce.isVisible()
            stopped = page.speech.stopped
            window.show_library()
            assert page.speech.stopped > stopped
            window.show_vocabulary()
            page.study.begin([vocabulary.get_word(word_id)], "card")
            page.study.reveal()
            if previews:
                QTest.qWait(240)
                assert window.grab().save(str(previews / "word-pronunciation.png"))
            page.show_library()
            page.edit_word()
            page.word.setText("hello")
            bad_profile = dict(profile, base_url="http://example.com")
            with patch.object(store, "get_profile", return_value=bad_profile):
                page.translate_editor()
                assert "HTTPS" in page.editor_status.text() and not page._translation_busy
            page.reset()
            assert page.import_table.rowCount() == 0 and page.views.currentWidget() is page.library
            assert not page.resume_import.isVisible()
            window.close()
    print("PASS: TXT/CSV, atomic import, translation validation/fallback/batches/retry/cancel, pronunciation/speed persistence/spelling, compact UI")


if __name__ == "__main__":
    check(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
