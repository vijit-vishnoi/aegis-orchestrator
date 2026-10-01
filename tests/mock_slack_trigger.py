import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from langgraph.types import Command
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from main import build_graph
import asyncio

async def run_mock_approval():
    print("=== MOCK SLACK APPROVAL TRIGGER ===")
    
    builder = build_graph()
    thread_id = sys.argv[1] if len(sys.argv) > 1 else "test-e2e-incident-001"
    thread_config = {"configurable": {"thread_id": thread_id}}
    
    db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "checkpoints.db"))

    async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
        graph = builder.compile(checkpointer=checkpointer)
        
        state = await graph.aget_state(thread_config)
        
        if not state.next:
            print(f"\n[ERROR] Graph is not in a paused state or the thread '{thread_id}' does not exist.")
            print("Please make sure `python tests/test_e2e_workflow.py` has been executed and is paused.")
            return

        print("\n[1] Checkpoint found. Graph is paused and awaiting input.")
        print("\n[2] Injecting mock 'Approve' payload to resume the graph...")
        
        resume_command = Command(resume={"action": "approve"})
        
        async for event in graph.astream(resume_command, config=thread_config):
            print(f"Event: {event}")

        final_state = await graph.aget_state(thread_config)
        print("\n=== E2E GRAPH EXECUTION COMPLETED ===")
        print("Final State Messages:")
        for msg in final_state.values.get("messages", []):
            print(f"- {msg.content}")

if __name__ == "__main__":
    asyncio.run(run_mock_approval())
