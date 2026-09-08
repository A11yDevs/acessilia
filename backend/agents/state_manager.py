import asyncio
import time
import uuid
from pathlib import Path

from backend.i18n import t
from backend.log_messages import LOG_TASK_CANCELLED_BY_USER
from backend.stage_messages import STAGE_CANCELLED_BY_USER


class StateManager:
    def __init__(self):
        self._tasks: dict[str, dict] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}

    def criar_tarefa(
        self, file_path: Path, task_id: str | None = None, arquivo: str | None = None
    ) -> str:
        task_id = task_id or str(uuid.uuid4())[:8]
        current = self._tasks.get(task_id)
        self._tasks[task_id] = {
            "task_id": task_id,
            "arquivo": arquivo or (current or {}).get("arquivo") or file_path.name,
            "status": "processing",
            "progresso": 0.0,
            "etapa_atual": "",
            "erros": [],
            "resultado": None,
            "inicio": time.time(),
            "fim": None,
        }
        self._cancel_events[task_id] = asyncio.Event()
        return task_id

    def atualizar(
        self,
        task_id: str,
        progresso: float | None = None,
        etapa: str | None = None,
        status: str | None = None,
        erro: str | None = None,
        resultado: str | None = None,
    ) -> None:
        task = self._tasks.get(task_id)
        if not task:
            return
        if task.get("status") == "cancelled":
            return
        if progresso is not None:
            task["progresso"] = progresso
        if etapa is not None:
            task["etapa_atual"] = etapa
        if status is not None:
            task["status"] = status
        if erro is not None:
            task["erros"].append(erro)
        if resultado is not None:
            task["resultado"] = resultado
        if status in ("done", "error"):
            task["fim"] = time.time()

    def obter(self, task_id: str) -> dict | None:
        return self._tasks.get(task_id)

    def finalizar(self, task_id: str, resultado: str) -> None:
        task = self._tasks.get(task_id)
        if not task or task.get("status") == "cancelled":
            return
        self.atualizar(task_id, progresso=1.0, status="done", resultado=resultado)

    def errar(self, task_id: str, erro: str) -> None:
        task = self._tasks.get(task_id)
        if not task or task.get("status") == "cancelled":
            return
        self.atualizar(task_id, status="error", erro=erro)

    def listar_tarefas(self) -> list[dict]:
        return list(self._tasks.values())

    def listar_tarefas_processing(self) -> list[dict]:
        return [t for t in self._tasks.values() if t.get("status") == "processing"]

    def cancelar(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and task.get("status") == "processing":
            task["status"] = "cancelled"
            task["etapa_atual"] = t(STAGE_CANCELLED_BY_USER)
            task["fim"] = time.time()
            event = self._cancel_events.get(task_id)
            if event:
                event.set()
            return True
        return False

    def foi_cancelada(self, task_id: str) -> bool:
        event = self._cancel_events.get(task_id)
        return event is not None and event.is_set()

    def verificar_cancelamento(self, task_id: str) -> None:
        """Check whether the given task was cancelled, raising a localized cancellation error when it was.

        Args:
            task_id (str): Task identifier whose cancellation event is inspected; no default (required).
        """
        if self.foi_cancelada(task_id):
            raise TaskCancelledError(
                t(LOG_TASK_CANCELLED_BY_USER).format(task_id=task_id)
            )

    def registrar_download_url(self, task_id: str, url: str) -> None:
        task = self._tasks.get(task_id)
        if task:
            task["download_url"] = url

    def expirar_tarefas_terminais(
        self, max_age_seconds: int, now: float | None = None
    ) -> int:
        now = now or time.time()
        expired = [
            task_id
            for task_id, task in self._tasks.items()
            if task.get("status") in ("done", "error", "cancelled")
            and task.get("fim") is not None
            and (now - task["fim"]) > max_age_seconds
        ]
        for task_id in expired:
            self._tasks.pop(task_id, None)
            self._cancel_events.pop(task_id, None)
        return len(expired)


class TaskCancelledError(Exception):
    pass


state_manager = StateManager()
