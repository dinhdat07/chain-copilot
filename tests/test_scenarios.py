import pytest

from core.enums import ApprovalStatus, Mode
from core.state import load_initial_state
from orchestrator.service import PendingApprovalError
from simulation.runner import ScenarioRunner


def test_daily_normal_plan_executes_without_disruption() -> None:
    state = load_initial_state()
    result = ScenarioRunner().graph.invoke(state, None)
    assert result.latest_plan is not None
    assert result.mode == Mode.NORMAL
    assert result.pending_plan is None


def test_supplier_delay_scenario_generates_plan() -> None:
    state = load_initial_state()
    runner = ScenarioRunner()
    result = runner.run(state, "supplier_delay")
    assert result.latest_plan is not None
    assert result.latest_plan.mode in {Mode.CRISIS, Mode.APPROVAL}
    assert result.decision_logs


def test_compound_disruption_requires_approval_or_crisis_plan() -> None:
    state = load_initial_state()
    runner = ScenarioRunner()
    result = runner.run(state, "compound_disruption")
    assert result.latest_plan is not None
    assert result.decision_logs[-1].approval_status in {
        ApprovalStatus.PENDING,
        ApprovalStatus.AUTO_APPLIED,
    }


def test_runner_blocks_new_scenario_when_approval_is_pending() -> None:
    state = load_initial_state()
    runner = ScenarioRunner()
    pending_state = runner.run(state, "supplier_delay")
    with pytest.raises(PendingApprovalError):
        runner.run(pending_state, "route_blockage")
