from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class _Signals(QObject):
    succeeded = Signal(object)
    failed = Signal(object)


class Worker(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = _Signals()

    @Slot()
    def run(self):
        try:
            self.signals.succeeded.emit(self.function())
        except Exception as error:
            self.signals.failed.emit(error)
