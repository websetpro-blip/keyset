"""Qt integration layer for streaming Turbo parser results into the UI."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Iterable, List, Optional, Dict

from PySide6.QtCore import QObject, QThread, Signal

try:
    from ..services.accounts import list_accounts
    from ..workers.turbo_parser_gui_wrapper import TurboParserGUI
    from ..core.models import Account
except ImportError:  # pragma: no cover - direct script execution
    from services.accounts import list_accounts
    from workers.turbo_parser_gui_wrapper import TurboParserGUI
    from core.models import Account  # type: ignore


@dataclass
class _JobConfig:
    phrases: List[str]
    account_name: Optional[str]
    region: int
    modes: Dict[str, bool]
    headless: bool = False


class _ParserWorker(QThread):
    """Background worker that runs TurboParserGUI inside a dedicated event loop."""

    result = Signal(str, dict)
    progress = Signal(int, int)
    log = Signal(str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, config: _JobConfig, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._config = config
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._parser: Optional[TurboParserGUI] = None
        self._results: List[dict] = []
        self._stop_requested = False

    # ------------------------------------------------------------------ threading plumbing
    def run(self) -> None:  # type: ignore[override]
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._run())
        finally:
            try:
                pending = asyncio.all_tasks(self._loop)
                for task in pending:
                    task.cancel()
                if pending:
                    self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            finally:
                self._loop.close()
                self._loop = None

    def request_stop(self) -> None:
        self._stop_requested = True
        if self._loop and self._parser:
            asyncio.run_coroutine_threadsafe(self._parser.stop(), self._loop)

    # ------------------------------------------------------------------ async helpers
    async def _run(self) -> None:
        account = self._resolve_account(self._config.account_name)
        
        # Получаем путь к профилю и прокси для аккаунта
        profile_path = f"C:\\AI\\yandex\\.profiles\\{account.name}" if account else "C:\\AI\\yandex\\.profiles\\wordstat_main"
        proxy_uri = getattr(account, "proxy", None) if account else None
        
        self._parser = TurboParserGUI(
            on_result=self._handle_result,
            on_progress=self._handle_progress,
            on_log=self._handle_log,
        )
        
        try:
            results = await self._parser.parse_phrases(
                account=account.name if account else "wordstat_main",
                profile_path=profile_path,
                phrases=self._config.phrases,
                modes=self._config.modes,
                region=self._config.region,
                proxy_uri=proxy_uri
            )
            if not self._stop_requested:
                # Преобразуем результаты в нужный формат
                formatted_results = [
                    {"phrase": phrase, **result}
                    for phrase, result in results.items()
                ]
                self.finished.emit(formatted_results)
        except Exception as exc:  # pragma: no cover - propagated to UI
            self.error.emit(str(exc))
        finally:
            try:
                await self._parser.stop()
            finally:
                self._parser = None
                if self._stop_requested:
                    self.finished.emit(self._results)

    # ------------------------------------------------------------------ callbacks
    def _handle_result(self, phrase: str, payload: Dict[str, object]) -> None:
        self._results.append(payload)
        self.result.emit(phrase, payload)

    def _handle_progress(self, current: int, total: int) -> None:
        self.progress.emit(current, total)

    def _handle_log(self, message: str) -> None:
        self.log.emit(message)

    @staticmethod
    def _resolve_account(name: Optional[str]) -> Optional[Account]:
        if not name:
            return None
        for account in list_accounts():
            if account.name == name:
                return account
        return None


class IntegrationService(QObject):
    """High-level service that exposes parser events via Qt signals."""

    onResult = Signal(str, dict)
    onProgress = Signal(int, int)
    onLog = Signal(str)
    onFinished = Signal(list)
    onError = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._worker: Optional[_ParserWorker] = None

    # ------------------------------------------------------------------ public API
    def is_running(self) -> bool:
        return bool(self._worker and self._worker.isRunning())

    def start_parsing(
        self,
        phrases: Iterable[str],
        account_name: Optional[str],
        region: int,
        modes: Dict[str, bool],
        *,
        headless: bool = False,
    ) -> None:
        if self.is_running():
            raise RuntimeError("Парсинг уже выполняется")

        config = _JobConfig(
            phrases=[phrase for phrase in phrases if phrase],
            account_name=account_name,
            region=region,
            modes=modes,
            headless=headless,
        )
        worker = _ParserWorker(config)
        worker.result.connect(self._handle_result)
        worker.progress.connect(self._handle_progress)
        worker.log.connect(self._handle_log)
        worker.finished.connect(self._handle_finished)
        worker.error.connect(self._handle_error)
        self._worker = worker
        worker.start()

    def stop_parsing(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.request_stop()

    # ------------------------------------------------------------------ signal forwarders
    def _handle_result(self, phrase: str, payload: dict) -> None:
        self.onResult.emit(phrase, payload)

    def _handle_progress(self, current: int, total: int) -> None:
        self.onProgress.emit(current, total)

    def _handle_log(self, message: str) -> None:
        self.onLog.emit(message)

    def _handle_finished(self, results: list) -> None:
        self.onFinished.emit(results)
        self._cleanup_worker()

    def _handle_error(self, message: str) -> None:
        self.onError.emit(message)
        self._cleanup_worker()

    def _cleanup_worker(self) -> None:
        if self._worker and not self._worker.isRunning():
            self._worker = None


__all__ = ["IntegrationService"]
