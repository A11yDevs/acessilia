import asyncio
import time
import uuid
from pathlib import Path


class StateManager:
    def __init__(self):
        self._tasks: dict[str, dict] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}

    def criar_tarefa(self, file_path: Path) -> str:
        task_id = str(uuid.uuid4())[:8]
        self._tasks[task_id] = {
            "task_id": task_id,
            "arquivo": file_path.name,
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

    def cancelar(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task and task.get("status") == "processing":
            task["status"] = "cancelled"
            task["etapa_atual"] = "Cancelado pelo usuario"
            task["fim"] = time.time()
            event = self._cancel_events.get(task_id)
            if event:
                event.set()

    def foi_cancelada(self, task_id: str) -> bool:
        event = self._cancel_events.get(task_id)
        return event is not None and event.is_set()

    def verificar_cancelamento(self, task_id: str) -> None:
        if self.foi_cancelada(task_id):
            raise TaskCancelledError(f"Tarefa {task_id} cancelada pelo usuario")


class TaskCancelledError(Exception):
    pass


state_manager = StateManager()
