import time

import pytest
import requests

BASE_URL = "http://127.0.0.1:8000/api/v1"


def _api_available() -> bool:
    try:
        requests.get("http://127.0.0.1:8000/", timeout=1)
    except requests.RequestException:
        return False
    return True


@pytest.mark.skipif(not _api_available(), reason="local API server is not running")
def test_metadata_with_event() -> None:
    print("=== STARTING API TEST: MEMORY RETRIEVAL ===")

    event_payload = {
        "type": "supplier_delay",
        "severity": 0.95,
        "source": "Manual Test",
        "entity_ids": ["SUP_BN"],
        "payload": {"reason": "Heavy storm at supplier location"},
    }

    print(f"\n1. Triggering event: {event_payload['type']} (severity {event_payload['severity']})...")
    response = requests.post(f"{BASE_URL}/events", json=event_payload, timeout=5)

    if response.status_code != 200:
        print(f"Error triggering event: {response.text}")
        return

    print("\n2. Fetching current control tower state to check metadata...")
    time.sleep(1)

    state_response = requests.get(f"{BASE_URL}/control-tower/summary", timeout=5)
    if state_response.status_code != 200:
        print(f"Error fetching state: {state_response.text}")
        return

    data = state_response.json()
    latest_plan = data.get("latest_plan")

    if not latest_plan:
        print("No plan generated yet.")
        return

    metadata = latest_plan.get("metadata", {})
    referenced_cases = metadata.get("referenced_cases", [])
    influence = metadata.get("memory_influence_score", 0.0)
    rationale = metadata.get("strategy_rationale", "")

    print("\n=== TEST RESULTS ===")
    print(f"Memory Status from API: {data.get('memory_status')}")
    print(f"Plan ID: {latest_plan.get('plan_id')}")
    print(f"Mode   : {data.get('mode')}")
    print(f"Memory Influence Score: {influence:.2f}")
    print(f"Referenced Case Count : {len(referenced_cases)}")

    if referenced_cases:
        print("Referenced Cases:")
        for case in referenced_cases:
            print(
                " - ID: "
                f"{case['case_id']} | Type: {case['event_type']} | "
                f"Similarity: {case.get('similarity_score', 'N/A')}"
            )
    else:
        print("!!! Still no cases matched. Need to check similarity logic.")

    print(f"\nStrategy Rationale: {rationale[:200]}...")


if __name__ == "__main__":
    try:
        test_metadata_with_event()
    except Exception as exc:
        print(f"Connection Error: {exc}. Make sure the uvicorn server is running on port 8000.")
