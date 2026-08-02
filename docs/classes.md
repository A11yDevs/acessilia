# Classes

## Objective
Catalog concrete classes in the repository and their responsibilities to support architectural evolution.

---

## Configuration and Domain Classes

### Settings
- File: [backend/config/settings.py](../backend/config/settings.py)
- Type: dataclass
- Responsibility: centralize environment variables, directories, processing limits, and interface toggles.
- Relationships: used across backend services, agents, and frontend bootstrap scripts.

### QueueItem
- File: [backend/services/queue_service.py](../backend/services/queue_service.py)
- Type: dataclass
- Responsibility: represent queued conversion requests with user, chat, and task metadata.

---

## Multi-Agent and Orchestration Classes

### AccessibilityOrchestrator
- File: [backend/agents/orchestrator.py](../backend/agents/orchestrator.py)
- Responsibility: coordinates multi-agent conversion lifecycle, cache checking, history logging, agent dispatching, and fallback mechanisms.
- Collaborators: `ReaderAgent`, `VisionAgent`, `DataAgent`, `EditorAgent`, `StateManager`, `ProcessingQueue`.

### ReaderAgent
- File: [backend/agents/reader_agent.py](../backend/agents/reader_agent.py)
- Responsibility: local-first PDF/image structural parsing (via PyMuPDF or Docling), page splitting, and region classification (`RegionTask`).

### VisionAgent
- File: [backend/agents/vision_agent.py](../backend/agents/vision_agent.py)
- Responsibility: Agno `Agent` wrapper for multimodal AI vision tasks, generating detailed alt-text and audio descriptions for visual content.

### DataAgent
- File: [backend/agents/data_agent.py](../backend/agents/data_agent.py)
- Responsibility: Agno `Agent` wrapper for complex data processing, converting tables and mathematical formulas into Markdown and LaTeX.

### EditorAgent
- File: [backend/agents/editor_agent.py](../backend/agents/editor_agent.py)
- Responsibility: content sanitization, MD5 fingerprint deduplication, and accessibility tag placement in the final document.

### StateManager
- File: [backend/agents/state_manager.py](../backend/agents/state_manager.py)
- Responsibility: create, update, finalize, cancel, and query in-memory task states.

### TaskCancelledError
- File: [backend/agents/state_manager.py](../backend/agents/state_manager.py)
- Responsibility: exception signaling task cancellation during execution.

### ProcessingQueue
- File: [backend/services/queue_service.py](../backend/services/queue_service.py)
- Responsibility: queue management and async concurrency control.

---

## Frontend & Interface Classes

### FeedbackStates
- File: [frontend/telegram/handlers/start.py](../frontend/telegram/handlers/start.py)
- Inheritance: `StatesGroup` (aiogram)
- Responsibility: control FSM state during user feedback collection.

### PauseMiddleware
- File: [frontend/telegram/middlewares/pause_middleware.py](../frontend/telegram/middlewares/pause_middleware.py)
- Inheritance: `BaseMiddleware` (aiogram)
- Responsibility: gate messages in paused Telegram chats.

### StatusTracker
- File: [frontend/telegram/adapters/status_tracker.py](../frontend/telegram/adapters/status_tracker.py)
- Responsibility: publish and update Telegram progress bars and status messages.

---

## Document Export Classes

### _DocTemplate
- File: [backend/export/renderers/pdf_renderer.py](../backend/export/renderers/pdf_renderer.py)
- Inheritance: `SimpleDocTemplate` (reportlab)
- Responsibility: generate accessible bookmarks and outline hierarchy in exported PDF files.

---

## Relationships Between Classes (Simplified View)

1. `Settings` is a global configuration dependency.
2. `AccessibilityOrchestrator` coordinates `ReaderAgent` for local structural parsing first, then dispatches `VisionAgent` and `DataAgent` for AI inference, and finishes with `EditorAgent` for consolidation.
3. `StateManager` and `ProcessingQueue` manage execution control and concurrency.
4. `StatusTracker` and `PauseMiddleware` extend Telegram interface runtime behavior.
5. Export renderers run after the canonical document pipeline validates the output.
