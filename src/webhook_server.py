import sys
import asyncio
from dotenv import load_dotenv

load_dotenv()

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
import uuid
import uvicorn
from fastapi import FastAPI, Request
from langchain_core.messages import HumanMessage
from main import get_graph

app = FastAPI()

async def process_alert(alert_data: dict):
    # Log the incoming alert
    target = alert_data.get("labels", {}).get("instance", "unknown")
    alertname = alert_data.get("labels", {}).get("alertname", "Unknown Alert")
    print(f"[Webhook] Processing alert: {alertname} on {target}")

    # Generate a unique thread ID for this incident
    thread_id = f"incident-{uuid.uuid4()}"
    config = {"configurable": {"thread_id": thread_id}}

    # Get the graph with persistent SqliteSaver
    graph = get_graph()

    # Trigger workflow with initial message based on alert
    msg = HumanMessage(content=f"Alert {alertname} fired for {target}. Please remediate.")
    initial_state = {"messages": [msg]}
    
    try:
        await asyncio.to_thread(graph.invoke, initial_state, config)
    except Exception as e:
        print(f"[Webhook] ERROR: Workflow for {thread_id} crashed with: {e}")

@app.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()
    
    # Prometheus Alertmanager standard JSON payload has an 'alerts' array
    alerts = payload.get("alerts", [])
    
    for alert in alerts:
        if alert.get("status") == "firing":
            # Crucial: Run graph invocation as background task to return 200 OK immediately
            asyncio.create_task(process_alert(alert))
            
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080, loop="asyncio")
