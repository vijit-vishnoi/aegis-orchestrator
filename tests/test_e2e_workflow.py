import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from langchain_core.messages import HumanMessage
from qdrant_client import QdrantClient
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
import knowledge_base
from main import build_graph
import asyncio

async def run_e2e_test():
    print("=== PHASE 2.5 INTEGRATION TEST ===")
    
    print("\n[1] Initializing in-memory Qdrant...")
    knowledge_base.client = QdrantClient(":memory:")
    knowledge_base.setup_collection()

    db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "checkpoints.db"))
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except OSError:
            pass

    builder = build_graph()
    thread_config = {"configurable": {"thread_id": "test-e2e-incident-001"}}

    print("\n[2] Submitting High CPU Alert to Supervisor...")
    initial_input = {"messages": [HumanMessage(content="High CPU Alert: Check metric")]}

    async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
        graph = builder.compile(checkpointer=checkpointer)

        async for event in graph.astream(initial_input, config=thread_config):
            print(f"Event: {event}")

        state = await graph.aget_state(thread_config)
        if state.next and state.tasks and state.tasks[0].interrupts:
            print("\n=== E2E GRAPH PAUSED AT REMEDIATION ===")
            print(f"Interrupt payload: {state.tasks[0].interrupts[0].value}")
            print("\n[3] The LangGraph orchestration successfully paused and is awaiting human approval.")
            print("To proceed, open another terminal and run:")
            print("  python tests/mock_slack_trigger.py")
        else:
            print("\n=== E2E FAILED TO REACH REMEDIATION ===")
            print("Graph did not pause or didn't reach the remediation node.")

if __name__ == "__main__":
    asyncio.run(run_e2e_test())
