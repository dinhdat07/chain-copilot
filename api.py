from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app_api.routers import create_router
from app_api.schemas import ErrorResponse
from app_api.services import ControlTowerRuntime, make_runtime
from core.memory import SQLiteStore
from core.state import load_initial_state, refresh_operational_baseline
from orchestrator.graph import build_graph
from simulation.runner import ScenarioRunner
from execution.dispatch_service import ActionDispatchService


def create_runtime(store: SQLiteStore | None = None) -> ControlTowerRuntime:
    """Creates the main engine instance."""
    return make_runtime(store=store)


def _cors_settings_from_env() -> tuple[list[str], bool]:
    """
    Reads CORS settings from env.

    CHAINCOPILOT_CORS_ORIGINS supports:
    - "*" (default): allow all origins (credentials disabled by spec)
    - comma-separated origins: credentials enabled
    """
    raw_origins = os.getenv("CHAINCOPILOT_CORS_ORIGINS", "*").strip()
    if raw_origins == "*":
        return ["*"], False

    origins = [
        origin.strip().rstrip("/")
        for origin in raw_origins.split(",")
        if origin.strip()
    ]
    if not origins:
        return ["*"], False
    return origins, True


# Global runtime instance
RUNTIME = create_runtime()

# Legacy globals for backward compatibility
STORE = RUNTIME.store
STATE = RUNTIME.state
GRAPH = RUNTIME.graph
RUNNER = RUNTIME.runner


def sync_legacy_globals() -> None:
    """Maintains alignment between the runtime and legacy global variables."""
    global STORE, STATE, GRAPH, RUNNER
    STORE = RUNTIME.store
    STATE = RUNTIME.state
    GRAPH = RUNTIME.graph
    RUNNER = RUNTIME.runner


def replace_runtime(
    *,
    store: SQLiteStore | None = None,
    state=None,
    graph=None,
    runner=None,
    dispatch_service=None,
) -> ControlTowerRuntime:
    """Reconfigures the service with fresh components."""
    global RUNTIME
    selected_store = store or SQLiteStore()
    RUNTIME = ControlTowerRuntime(
        store=selected_store,
        state=state or refresh_operational_baseline(load_initial_state()),
        graph=graph or build_graph(),
        runner=runner or ScenarioRunner(store=selected_store),
        dispatch_service=dispatch_service or ActionDispatchService(),
    )
    sync_legacy_globals()
    return RUNTIME


def create_app(runtime: ControlTowerRuntime | None = None) -> FastAPI:
    """Application factory for the ChainCopilot API."""
    print(">>> CALLING create_app")
    if runtime is not None:

        replace_runtime(
            store=runtime.store,
            state=runtime.state,
            graph=runtime.graph,
            runner=runtime.runner,
            dispatch_service=runtime.dispatch_service,
        )
    instance = FastAPI(title="ChainCopilot API", version="0.2.0")
    
    cors_origins, cors_allow_credentials = _cors_settings_from_env()
    instance.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @instance.get("/health")
    def health():
        return {"status": "ok", "version": "0.2.0-ws-debug"}

    # Modular routers - Includes all /api/v1 endpoints

    instance.include_router(create_router(lambda: RUNTIME), prefix="/api/v1")

    # Direct WebSocket route (UNIQUE PATH - NO PREFIX)
    print(">>> REGISTERING WEBSOCKET: /thinking-stream/{run_id}")
    @instance.websocket("/thinking-stream/{run_id}")
    async def thinking_stream(websocket: WebSocket, run_id: str) -> None:
        from streaming.event_bus import event_bus
        await websocket.accept()
        try:
            async for thinking_event in event_bus.subscribe(run_id):
                await websocket.send_text(thinking_event.model_dump_json())
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            try:
                await websocket.close()
            except Exception:
                pass

    register_error_handlers(instance)
    return instance


def _error_code_for_status(status_code: int) -> str:
    return {
        404: "not_found",
        409: "conflict",
        422: "validation_error",
        500: "system_error",
    }.get(status_code, "request_error")


def _error_response(status_code: int, detail) -> JSONResponse:
    if isinstance(detail, ErrorResponse):
        payload = detail
    elif isinstance(detail, dict):
        payload = ErrorResponse(
            code=str(detail.get("code") or _error_code_for_status(status_code)),
            message=str(detail.get("message") or "request failed"),
            details=detail.get("details", {}),
            retryable=bool(detail.get("retryable", False)),
            correlation_id=detail.get("correlation_id"),
        )
    else:
        payload = ErrorResponse(
            code=_error_code_for_status(status_code),
            message=str(detail or "request failed"),
        )
    return JSONResponse(status_code=status_code, content=jsonable_encoder(payload))


def register_error_handlers(instance: FastAPI) -> None:
    @instance.exception_handler(HTTPException)
    async def _http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
        return _error_response(exc.status_code, exc.detail)

    @instance.exception_handler(RequestValidationError)
    async def _validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(
            422,
            {
                "code": "validation_error",
                "message": "request validation failed",
                "details": {"errors": exc.errors()},
                "retryable": False,
            },
        )

    @instance.exception_handler(Exception)
    async def _unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
        return _error_response(
            500,
            {
                "code": "system_error",
                "message": "internal server error",
                "details": {"exception_type": exc.__class__.__name__},
                "retryable": False,
            },
        )


sync_legacy_globals()
app = create_app(RUNTIME)

@app.get("/health-module")
def health_module():
    return {"status": "ok", "source": "module-level"}
