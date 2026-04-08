# Architecture

ChainCopilot uses a six-layer event-driven control tower architecture:

1. Streamlit dashboard
2. FastAPI control tower app layer
3. Event and state bus
4. Lightweight digital twin
5. Agent orchestration layer
6. Deterministic decision policy engine

The system is stateful and built around the loop:

Sense -> Analyze -> Plan -> Act -> Learn
