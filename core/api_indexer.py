from __future__ import annotations

from qgis.PyQt.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal


class _Signals(QObject):
    finished = pyqtSignal(bool, str, int)
    failed = pyqtSignal(str)


class ApiIndexWorker(QRunnable):
    def __init__(self, language_service, force=False):
        super().__init__()
        self.service = language_service
        self.force = force
        self.signals = _Signals()
        self.setAutoDelete(True)

    def run(self):
        try:
            if self.force:
                self.service.reset_index()
            self.service.ensure_indexed()
            self.signals.finished.emit(
                True,
                "Indicizzazione API QGIS completata.",
                len(self.service.symbols),
            )
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class ApiIndexer:
    def __init__(self, service):
        self.service = service
        self.pool = QThreadPool.globalInstance()
        self.worker = None

    def start(self, force=False):
        if self.worker is not None:
            return False, self.worker.signals
        self.worker = ApiIndexWorker(self.service, force)
        signals = self.worker.signals
        signals.finished.connect(self._done)
        signals.failed.connect(self._failed)
        self.pool.start(self.worker)
        return True, signals

    def _done(self, *_):
        self.worker = None

    def _failed(self, *_):
        self.worker = None
