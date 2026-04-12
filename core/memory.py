from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from core.models import DecisionLog, OrchestrationTrace, ScenarioRun, SystemState
from core.runtime_records import EventEnvelope, ExecutionRecord, RunRecord


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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS event_log (
                    event_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS run_records (
                    run_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS traces (
                    run_id TEXT PRIMARY KEY,
                    trace_id TEXT,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_records (
                    execution_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS action_execution_records (
                    execution_id TEXT PRIMARY KEY,
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

    def get_decision_log(self, decision_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM decision_logs WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
        return None if row is None else json.loads(row[0])

    def save_scenario_run(self, run: ScenarioRun) -> None:
        payload = json.dumps(run.model_dump(mode="json"), ensure_ascii=True)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO scenario_runs(scenario_id, payload) VALUES(?, ?)",
                (run.run_id, payload),
            )

    def save_event_envelope(self, event: EventEnvelope) -> None:
        payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=True)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO event_log(event_id, payload) VALUES(?, ?)",
                (event.event_id, payload),
            )

    def get_event_envelope(self, event_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM event_log WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return None if row is None else json.loads(row[0])

    def list_event_envelopes(self, limit: int | None = None) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload FROM event_log").fetchall()
        items = [json.loads(row[0]) for row in rows]
        items.sort(key=lambda item: item.get("ingested_at", ""), reverse=True)
        if limit is None or limit < 0:
            return items
        return items[:limit]

    def save_run_record(self, run: RunRecord) -> None:
        payload = json.dumps(run.model_dump(mode="json"), ensure_ascii=True)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO run_records(run_id, payload) VALUES(?, ?)",
                (run.run_id, payload),
            )

    def get_run_record(self, run_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM run_records WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return None if row is None else json.loads(row[0])

    def list_run_records(self, limit: int | None = None) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload FROM run_records").fetchall()
        items = [json.loads(row[0]) for row in rows]
        items.sort(key=lambda item: item.get("started_at", ""), reverse=True)
        if limit is None or limit < 0:
            return items
        return items[:limit]

    def get_state_snapshot(self, run_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM state_snapshots WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return None if row is None else json.loads(row[0])

    def save_trace(self, run_id: str, trace: OrchestrationTrace) -> None:
        payload = json.dumps(trace.model_dump(mode="json"), ensure_ascii=True)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO traces(run_id, trace_id, payload) VALUES(?, ?, ?)",
                (run_id, trace.trace_id, payload),
            )

    def get_trace(self, run_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM traces WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return None if row is None else json.loads(row[0])

    def list_traces(self, limit: int | None = None) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload FROM traces").fetchall()
        items = [json.loads(row[0]) for row in rows]
        items.sort(key=lambda item: item.get("started_at", ""), reverse=True)
        if limit is None or limit < 0:
            return items
        return items[:limit]

    def save_execution_record(self, execution: ExecutionRecord) -> None:
        payload = json.dumps(execution.model_dump(mode="json"), ensure_ascii=True)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO execution_records(execution_id, payload) VALUES(?, ?)",
                (execution.execution_id, payload),
            )

    def get_execution_record(self, execution_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM execution_records WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
        return None if row is None else json.loads(row[0])

    def list_execution_records(self, limit: int | None = None) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload FROM execution_records").fetchall()
        items = [json.loads(row[0]) for row in rows]
        items.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        if limit is None or limit < 0:
            return items
        return items[:limit]

    def save_action_execution_record(self, execution_id: str, payload_dict: dict) -> None:
        payload = json.dumps(payload_dict, ensure_ascii=True)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO action_execution_records(execution_id, payload) VALUES(?, ?)",
                (execution_id, payload),
            )

    def get_action_execution_record(self, execution_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM action_execution_records WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
        return None if row is None else json.loads(row[0])

    def list_action_execution_records(self, limit: int | None = None) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload FROM action_execution_records").fetchall()
        items = [json.loads(row[0]) for row in rows]
        items.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        if limit is None or limit < 0:
            return items
        return items[:limit]

    def clear_all(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM decision_logs")
            conn.execute("DELETE FROM state_snapshots")
            conn.execute("DELETE FROM scenario_runs")
            conn.execute("DELETE FROM event_log")
            conn.execute("DELETE FROM run_records")
            conn.execute("DELETE FROM traces")
            conn.execute("DELETE FROM execution_records")
            conn.execute("DELETE FROM action_execution_records")
