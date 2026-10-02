# Aegis Orchestrator

**Event-Driven, Human-in-the-Loop Infrastructure Auto-Remediation Pipeline**

Aegis Orchestrator is a production-grade infrastructure healing system. It autonomously monitors container health, evaluates anomalies using directed graph workflows, requests asynchronous human approval via Slack, and safely executes host-level remediation commands. 

Built to handle decoupled, highly concurrent event processing, Aegis leverages a shared PostgreSQL state store to bridge the gap between asynchronous alert ingestion and interactive human-in-the-loop (HITL) execution.

---

## 🏗️ System Architecture

The pipeline consists of strictly decoupled services communicating via webhooks, shared database checkpoints, and the Model Context Protocol (MCP).

1. **Detection (Prometheus & Alertmanager):** Scrapes host metrics continuously. Upon breaching a threshold (e.g., CPU > 10%), Alertmanager fires a payload to the orchestrator.
2. **Ingestion (FastAPI):** A high-performance webhook server catches the alert and triggers the remediation workflow in an isolated background thread to prevent blocking the ASGI event loop.
3. **Orchestration (LangGraph):** The alert routes through a directed acyclic graph (DAG) that analyzes the incident, proposes a remediation step, and safely **pauses** execution, persisting its exact state to PostgreSQL.
4. **Human-in-the-Loop (Slack Bolt):** An interactive Slack message is dispatched to the engineering team with `Approve` and `Reject` actions.
5. **Resumption & Remediation (MCP):** A separate Slack listener process catches the user's decision, reads the paused thread from PostgreSQL, and resumes the graph. If approved, it leverages an MCP client to securely execute a `docker restart` on the affected container.

---

## 🛠️ Tech Stack

*   **API & Webhooks:** FastAPI, Uvicorn
*   **Workflow Engine:** LangGraph, LangChain
*   **State Persistence:** PostgreSQL (`PostgresSaver`)
*   **Monitoring & Alerting:** Prometheus, Alertmanager
*   **Human-in-the-Loop:** Slack Bolt Framework (Socket Mode)
*   **Host Execution:** Model Context Protocol (MCP) Client/Server
*   **Containerization:** Docker, Docker Compose

---

## 🚀 Key Engineering Highlights

### Decoupled State Management
A standard challenge in event-driven automation is handling the gap between when a webhook arrives and when a human actually clicks "Approve" hours later. 
Aegis solves this by decoupling the **Ingestion Server** (`webhook_server.py`) and the **Interaction Worker** (`slack_app.py`). Both processes share a unified **PostgreSQL checkpointer**. The webhook server creates the incident thread and suspends it to the DB; the Slack worker later hydrates that exact thread from the DB and finishes the execution.

### Event Loop Synchronization
To ensure maximum cross-platform compatibility (specifically bypassing the notorious Windows `ProactorEventLoop` vs. `psycopg` async conflict), the orchestrator utilizes synchronous DB connections routed through asynchronous `asyncio.to_thread` wrappers. This guarantees thread-safe, non-blocking FastAPI performance without sacrificing robust database connection pooling.

### Graceful Degradation & Rejection
The workflow fully supports negative paths. If an engineer rejects a remediation proposal via Slack, the system catches the unhandled action, acknowledges the rejection, strips the UI buttons to prevent double-clicks, and resumes the graph with an abort signal—bypassing the MCP execution node entirely.

---

## ⚙️ Local Setup & Testing

### 1. Prerequisites
* Docker & Docker Compose
* Python 3.10+
* A Slack Workspace with an installed App (requires `xoxb-` Bot Token and `xapp-` App Token)
* PostgreSQL running locally or in Docker

### 2. Environment Variables
Create a `.env` file in the root directory:
```env
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token
SLACK_CHANNEL_ID=your-channel-id
POSTGRES_URI=postgresql://postgres:postgres@localhost:5432/aegis
```

### 3. Start the Infrastructure
Boot up the target application, Prometheus, and Alertmanager:
```bash
docker compose up -d
```

### 4. Run the Orchestrator Services
In Terminal 1, start the webhook ingestion server:
```bash
python src/webhook_server.py
```

In Terminal 2, start the Slack interaction listener:
```bash
python src/slack_app.py
```

### 5. Trigger an Incident
Simulate a critical CPU spike on the target container using the built-in chaos endpoint:
```bash
curl http://localhost:8000/chaos/cpu
```
Within 5 to 10 seconds, Prometheus will detect the spike, Alertmanager will fire the webhook, and an approval request will appear in your Slack channel. Click Approve to watch the orchestrator autonomously restart the target container via Docker MCP.
