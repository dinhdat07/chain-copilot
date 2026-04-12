# Fix Windows Uvicorn Reload

## Objective

Prevent local FastAPI development startup from failing on Windows when Uvicorn reload scans the repository root and hits the `.venv/lib64` symlink.

## Scope

- [x] Add a dedicated backend dev runner with scoped reload directories
- [x] Keep application behavior unchanged
- [x] Update local startup instructions to use the safer command
- [x] Verify the new command starts without scanning `.venv`

## Files To Modify

- [x] `run_api.py`
- [x] `README.md`
- [x] `docs/internal/fix-windows-uvicorn-reload.md`

## Implementation Steps

- [x] Define the backend directories that should trigger reload
- [x] Add a small Python runner that calls `uvicorn.run(...)`
- [x] Point README API instructions to the new runner
- [x] Smoke test local startup

## Testing Approach

- [x] Start the API with the new command
- [x] Confirm no `.venv/lib64` reload crash occurs
- [x] Confirm the API process boots successfully
