import asyncio
from fastapi import FastAPI, WebSocket
import uvicorn
import websockets
from multiprocessing import Process
import time

app = FastAPI()

@app.websocket("/ws/{run_id}")
async def ws_endpoint(websocket: WebSocket, run_id: str):
    await websocket.accept()
    await websocket.send_text(f"Hello, {run_id}")
    await websocket.close()

def run_server():
    uvicorn.run(app, host="127.0.0.1", port=8005)

async def test_client():
    uri = "ws://127.0.0.1:8005/ws/abc"
    print(f"Connecting to {uri}")
    try:
        async with websockets.connect(uri) as websocket:
            msg = await websocket.recv()
            print("Received:", msg)
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    p = Process(target=run_server)
    p.start()
    time.sleep(2) # Give it time to start
    asyncio.run(test_client())
    p.terminate()
    p.join()
