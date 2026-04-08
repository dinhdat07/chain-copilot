from core.state import load_initial_state, state_summary
from simulation.runner import ScenarioRunner


def main() -> None:
    state = load_initial_state()
    runner = ScenarioRunner()
    final_state = runner.run(state, "supplier_delay")
    print("ChainCopilot quick run")
    print(state_summary(final_state))


if __name__ == "__main__":
    main()
