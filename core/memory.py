from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from core.models import DecisionLog, ScenarioRun, SystemState


class SQLiteStore:
    def __init__(self, path: str | Path = "chaincopilot.db") -> None:
        self.path = str(path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS decision_logs (
                    decision_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS state_snapshots (
                    run_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scenario_runs (
                    scenario_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )

    def save_state(self, state: SystemState) -> None:
        payload = json.dumps(state.model_dump(mode="json"), ensure_ascii=True)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO state_snapshots(run_id, payload) VALUES(?, ?)",
                (state.run_id, payload),
            )

    def save_decision_log(self, decision_log: DecisionLog) -> None:
        payload = json.dumps(decision_log.model_dump(mode="json"), ensure_ascii=True)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO decision_logs(decision_id, payload) VALUES(?, ?)",
                (decision_log.decision_id, payload),
            )

    def list_decision_logs(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM decision_logs ORDER BY decision_id DESC"
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def save_scenario_run(self, run: ScenarioRun) -> None:
        payload = json.dumps(run.model_dump(mode="json"), ensure_ascii=True)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO scenario_runs(scenario_id, payload) VALUES(?, ?)",
                (run.run_id, payload),
            )

    def clear_all(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM decision_logs")
            conn.execute("DELETE FROM state_snapshots")
            conn.execute("DELETE FROM scenario_runs")
