from __future__ import annotations

from fastapi import FastAPI

from app_api.routers import create_router
from app_api.services import ControlTowerRuntime, make_runtime
from core.memory import SQLiteStore
from core.state import load_initial_state
from orchestrator.graph import build_graph
from simulation.runner import ScenarioRunner


def create_runtime(store: SQLiteStore | None = None) -> ControlTowerRuntime:
    return make_runtime(store=store)


RUNTIME = create_runtime()


def sync_legacy_globals() -> None:
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
    global RUNTIME
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
    if runtime is not None:
        replace_runtime(
            store=runtime.store,
            state=runtime.state,
            graph=runtime.graph,
            runner=runtime.runner,
        )
    instance = FastAPI(title="ChainCopilot API", version="0.2.0")
    instance.include_router(create_router(lambda: RUNTIME))
    return instance


sync_legacy_globals()
app = create_app(RUNTIME)
