import asyncio
import json
import httpx
import websockets

async def test_realtime_v2():
    url = "http://localhost:8000/api/v1/plan/daily/stream"
    
    print("--- 1. Triggering stream via HTTP POST ---")
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, timeout=10.0)
            data = response.json()
        except Exception:
            print("Error: Could not connect to server at localhost:8000. Did you start uvicorn?")
            return

    run_id = data["run_id"]
    # WebSocket endpoint includes the /api/v1 prefix
    ws_url = f"ws://localhost:8000/api/v1/ws/thinking/{run_id}"
    
    print(f"Run ID: {run_id}")
    print(f"Connecting to: {ws_url}\n")

    print("--- 2. Listening to Live Thinking Steps ---")
    try:
        async with websockets.connect(ws_url) as websocket:
            while True:
                message = await websocket.recv()
                event = json.loads(message)
                
                seq = event.get("sequence", 0)
                agent = event.get("agent", "unknown")
                step = event.get("step", "unknown")
                msg = event.get("message", "")
                
                print(f"[{seq}] {agent.upper()} > {step}: {msg}")
                
                if event.get("type") == "final":
                    print("\n--- Stream Finished ---")
                    break
    except websockets.exceptions.ConnectionClosed:
        print("\nConnection closed.")
    except Exception as e:
        print(f"Error during streaming: {e}")

if __name__ == "__main__":
    asyncio.run(test_realtime_v2())



