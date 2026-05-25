# Classes

## Objective
Catalog concrete classes in the repository and their responsibilities to support architectural evolution.

## Configuration and domain classes

## Settings
- File: [config/settings.py](../config/settings.py)
- Type: dataclass
- Responsibility: centralize environment variables, directories, and processing limits.
- Relationships: used by nearly all runtime modules.

## QueueItem
- File: [bot/services/queue_service.py](../bot/services/queue_service.py)
- Type: dataclass
- Responsibility: represent queue items with user/chat/task metadata.

## Runtime and orchestration classes

## AgenteUnico
- File: [bot/agents/agente_unico.py](../bot/agents/agente_unico.py)
- Responsibility: page-by-page pipeline, image preprocessing, AI client invocation, and result aggregation.
- Collaborators: cache, image_converter, image_enhancer, pdf_splitter, selected AI client.

## StateManager
- File: [bot/agents/state_manager.py](../bot/agents/state_manager.py)
- Responsibility: create, update, finalize, cancel, and query in-memory task states.

## TaskCancelledError
- File: [bot/agents/state_manager.py](../bot/agents/state_manager.py)
- Responsibility: signal cancellation during processing.

## ProcessingQueue
- File: [bot/services/queue_service.py](../bot/services/queue_service.py)
- Responsibility: control queue and processing concurrency.

## External API integration

## OpenCodeClient
- File: [bot/clients/opencode.py](../bot/clients/opencode.py)
- Responsibility: OpenCode session management, multimodal message sending, retries, and response text extraction.

## OpenRouterClient
- File: [bot/clients/openrouter.py](../bot/clients/openrouter.py)
- Responsibility: OpenRouter API calls (multimodal chat completions) with retries and partial response handling.

## Telegram interface

## FeedbackStates
- File: [bot/handlers/start.py](../bot/handlers/start.py)
- Inheritance: StatesGroup
- Responsibility: control FSM state for feedback collection.

## PauseMiddleware
- File: [bot/middlewares/pause_middleware.py](../bot/middlewares/pause_middleware.py)
- Inheritance: BaseMiddleware
- Responsibility: block messages in paused chats, except reactivation command.

## StatusTracker
- File: [bot/utils/status_tracker.py](../bot/utils/status_tracker.py)
- Responsibility: publish/edit Telegram progress messages during processing.

## Document export

## _OutlineDocTemplate
- File: [bot/exporters/pdf_exporter.py](../bot/exporters/pdf_exporter.py)
- Inheritance: SimpleDocTemplate
- Responsibility: create accessible bookmark/outline structure in final PDF.

## Relationship between classes (simplified view)
1. Settings is a global configuration dependency.
2. AgenteUnico depends on OpenCodeClient/OpenRouterClient and image/PDF utilities.
3. StateManager and ProcessingQueue support execution control.
4. StatusTracker and PauseMiddleware extend aiogram runtime behavior.
5. Exporters run after AgenteUnico pipeline completion.

## Missing classes expected by runtime condition
- Observed reference: [bot.clients.browser_client](../bot/clients) (in [bot/agents/agente_unico.py](../bot/agents/agente_unico.py))
- Current status: module/class not found in this repository.
- Impact: setting AI_CLIENT=browser is likely to fail at import time.
