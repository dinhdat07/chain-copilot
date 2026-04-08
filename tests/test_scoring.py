from core.enums import Mode
from policies.scoring import compute_score


def test_crisis_mode_rewards_recovery_more_than_normal() -> None:
    normal, _ = compute_score(
        service_level=0.95,
        total_cost=100.0,
        disruption_risk=0.40,
        recovery_speed=0.90,
        mode=Mode.NORMAL,
        baseline_cost=100.0,
    )
    crisis, _ = compute_score(
        service_level=0.95,
        total_cost=100.0,
        disruption_risk=0.40,
        recovery_speed=0.90,
        mode=Mode.CRISIS,
        baseline_cost=100.0,
    )
    assert crisis > normal
