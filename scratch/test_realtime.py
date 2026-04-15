import asyncio
import json
import sys
import os

# Add current directory to path so 'api' can be imported
sys.path.append(os.getcwd())

from fastapi.testclient import TestClient
from api import app

def test_websocket_stream():
    client = TestClient(app)
    
    print("--- 1. Triggering stream ---")
    response = client.post("/api/v1/plan/daily/stream")
    data = response.json()
    run_id = data["run_id"]
    ws_url = data["ws_url"]
    print(f"Run ID: {run_id}")
    print(f"WS URL: {ws_url}\n")

    print("--- 2. Connecting to WebSocket & Listening ---")
    # Sử dụng TestClient để connect websocket
    with client.websocket_connect(ws_url) as websocket:
        try:
            while True:
                # Đợi nhận message
                message = websocket.receive_text()
                event = json.loads(message)
                
                # In ra format đẹp
                seq = event.get("sequence", 0)
                agent = event.get("agent", "unknown")
                step = event.get("step", "unknown")
                msg = event.get("message", "")
                
                print(f"[{seq}] {agent.upper()} > {step}: {msg}")
                
                if event.get("type") == "final":
                    print("\n--- Stream Finished Automatically ---")
                    break
        except Exception as e:
            print(f"\nConnection closed or error: {e}")

if __name__ == "__main__":
    test_websocket_stream()
