# Feature Plan: Mock Data Alignment

- [x] Inspect enriched mock data diffs and identify broken references.
- [x] Align scenario seed events with the enriched inventory and supplier IDs.
- [x] Align supporting seed tables (`orders.csv`, `warehouses.csv`) with the enriched inventory.
- [x] Add deterministic loader validation for seed-data referential integrity.
- [x] Update brittle tests that hardcode the old 3-SKU and 8-case seed assumptions.
- [x] Run targeted backend tests against the enriched dataset.
- [x] Update this checklist after verification.

## Files Expected To Change

- `docs/internal/feat-mock-data-alignment.md`
- `core/state.py`
- `data/historical_cases.csv`
- `data/inventory.csv`
- `data/suppliers.csv`
- `simulation/scenarios.py`
- `data/orders.csv`
- `data/warehouses.csv`
- `tests/test_strategic_prompt.py`
- `tests/test_explainability_learning.py`
- `tests/test_seed_data_alignment.py`
