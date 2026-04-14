# ChainCopilot

ChainCopilot is a hackathon MVP for an autonomous resilient supply chain control tower.
It implements a stateful agentic loop:

- Sense
- Analyze
- Plan
- Act
- Learn

The MVP includes:

- 6-layer control-tower architecture
- Demand, Inventory, Supplier, Logistics, Risk, and Planner agents
- Normal and crisis modes with deterministic policy switching
- Decision logs with explainability
- What-if scenario simulation
- Streamlit dashboard and FastAPI service

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
streamlit run ui/dashboard.py
```

## API

```bash
python run_api.py
```

## Scenarios

- supplier_delay
- demand_spike
- route_blockage
- compound_disruption
