from core.enums import Mode
from core.state import load_initial_state
from simulation.runner import ScenarioRunner
from ui.components import (
    demo_flow_dataframe,
    kpi_delta_dataframe,
    mode_summary,
    selected_action_summary,
)


def test_mode_summary_reflects_normal_state() -> None:
    summary = mode_summary(load_initial_state())
    assert summary["label"] == "Normal Mode"
    assert summary["tone"] == "success"


def test_demo_flow_dataframe_reflects_pending_approval() -> None:
    state = ScenarioRunner().run(load_initial_state(), "supplier_delay")
    flow = demo_flow_dataframe(state)
    rows = {row["step"]: row for row in flow.to_dict(orient="records")}

    assert rows["1. Daily plan"]["status"] == "complete"
    assert rows["2. Disruption detected"]["status"] == "complete"
    assert rows["3. Autonomous replan"]["status"] == "complete"
    assert rows["4. Approval workflow"]["status"] == "waiting for approval"
    assert rows["5. Learn from outcomes"]["status"] == "complete"
    assert state.mode in {Mode.APPROVAL, Mode.CRISIS}


def test_selected_action_summary_prefers_non_no_op_action() -> None:
    state = ScenarioRunner().graph.invoke(load_initial_state(), None)
    summary = selected_action_summary(state.latest_plan)

    assert summary is not None
    assert "No Op" not in summary["title"]
    assert "Service" in summary["impact"]


def test_kpi_delta_dataframe_contains_expected_metrics() -> None:
    state = load_initial_state()
    simulated = ScenarioRunner().graph.invoke(load_initial_state(), None)
    frame = kpi_delta_dataframe(state.kpis, simulated.kpis)

    assert set(frame["metric"]) == {
        "service_level",
        "total_cost",
        "disruption_risk",
        "recovery_speed",
        "stockout_risk",
    }
