from __future__ import annotations

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app_api.routers import create_router
from app_api.schemas import ErrorResponse
from app_api.services import ControlTowerRuntime, make_runtime
from core.memory import SQLiteStore


def create_runtime(store: SQLiteStore | None = None) -> ControlTowerRuntime:
    """Creates the main engine instance."""
    return make_runtime(store=store)


# Global runtime instance
RUNTIME = create_runtime()

# Legacy globals for backward compatibility (optional but kept for internal use if needed)
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
) -> ControlTowerRuntime:
    """Reconfigures the service with fresh components."""
    global RUNTIME
    from core.state import load_initial_state
    from orchestrator.graph import build_graph
    from simulation.runner import ScenarioRunner
    
    selected_store = store or SQLiteStore()
    RUNTIME = ControlTowerRuntime(
        store=selected_store,
        state=state or load_initial_state(),
        graph=graph or build_graph(),
        runner=runner or ScenarioRunner(store=selected_store),
    )
    sync_legacy_globals()
    return RUNTIME


def create_app(runtime: ControlTowerRuntime | None = None) -> FastAPI:
    """Application factory for the ChainCopilot API."""
    if runtime is not None:
        replace_runtime(
            store=runtime.store,
            state=runtime.state,
            graph=runtime.graph,
            runner=runtime.runner,
        )
    instance = FastAPI(title="ChainCopilot API", version="0.2.0")

    # Modular routers - Includes all /api/v1 endpoints (legacy, execution, etc.)
    instance.include_router(create_router(lambda: RUNTIME))

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


app = create_app(RUNTIME)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
