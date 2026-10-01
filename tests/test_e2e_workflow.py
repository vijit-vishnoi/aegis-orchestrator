import sys
import asyncio
import warnings

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore
import os
from dotenv import load_dotenv
load_dotenv()

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from langchain_core.messages import HumanMessage
from qdrant_client import QdrantClient
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
import knowledge_base
from main import build_graph

                                                                 
DB_URI = os.environ.get("DB_URI", "postgresql://postgres:postgrespassword@localhost:5432/aegis")

async def run_e2e_test():
    print("=== PHASE 3 INTEGRATION TEST ===")
    
    print("\n[1] Initializing in-memory Qdrant...")
    knowledge_base.client = QdrantClient(":memory:")
    knowledge_base.setup_collection()

    builder = build_graph()
    import uuid
    thread_id = f"incident-{uuid.uuid4().hex[:8]}"
    thread_config = {"configurable": {"thread_id": thread_id}}

    print("\n[2] Submitting High CPU Alert to Supervisor...")
    initial_input = {"messages": [HumanMessage(content="High CPU Alert: Check metric")]}

                                                   
    async with AsyncPostgresSaver.from_conn_string(DB_URI) as checkpointer:
        await checkpointer.setup()
        graph = builder.compile(checkpointer=checkpointer)

        async for event in graph.astream(initial_input, config=thread_config):
            print(f"Event: {event}")

        state = await graph.aget_state(thread_config)
        if state.next and state.tasks and state.tasks[0].interrupts:
            print("\n=== E2E GRAPH PAUSED AT REMEDIATION ===")
            print(f"Interrupt payload: {state.tasks[0].interrupts[0].value}")
            print("\n[3] The LangGraph orchestration successfully paused and is awaiting human approval.")
            print("Check your configured Slack channel for the interactive approval message!")
            print(f"To proceed, you can either approve directly in Slack OR run `python tests/mock_slack_trigger.py {thread_id}`.")
        else:
            print("\n=== E2E FAILED TO REACH REMEDIATION ===")
            print("Graph did not pause or didn't reach the remediation node.")

if __name__ == "__main__":
    asyncio.run(run_e2e_test())
