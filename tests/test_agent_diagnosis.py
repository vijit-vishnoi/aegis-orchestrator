import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from langchain_core.messages import HumanMessage
from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver
from main import build_graph

def test_graph_diagnosis_and_interrupt():
    print("=== TESTING AEGIS AGENT DIAGNOSIS WORKFLOW ===", flush=True)
    
    builder = build_graph()
    checkpointer = MemorySaver()
    graph = builder.compile(checkpointer=checkpointer)
    
    thread_id = "test-diagnostic-incident-101"
    config = {"configurable": {"thread_id": thread_id}}
    
    alert_msg = HumanMessage(
        content="Alertmanager Alert: 'HighCPU' fired for container 'target_app'. Annotations: CPU usage exceeded 85%. Please investigate root cause and propose remediation."
    )
    initial_state = {
        "messages": [alert_msg],
        "alert_summary": "HighCPU on target_app",
        "target_container": "target_app"
    }
    
    print("\n[Step 1] Invoking graph with alert...", flush=True)
    for event in graph.stream(initial_state, config=config):
        print(f"Event node output: {list(event.keys())}", flush=True)
        
    state = graph.get_state(config)
    print(f"\n[Step 2] Paused state tasks: {len(state.tasks)}", flush=True)
    assert state.tasks and state.tasks[0].interrupts, "Graph should be paused at execute_remediation interrupt!"
    
    interrupt_val = state.tasks[0].interrupts[0].value
    print(f"Interrupt Payload: {interrupt_val}", flush=True)
    print(f"Captured Diagnosis: {state.values.get('diagnosis_reasoning')}", flush=True)
    print(f"Captured Proposed Action: {state.values.get('proposed_action')}", flush=True)
    
    assert state.values.get("diagnosis_reasoning"), "diagnosis_reasoning must be present in state!"
    assert state.values.get("proposed_action"), "proposed_action must be present in state!"
    assert state.values.get("approval_dispatched") is True, "approval_dispatched should be True!"
    
    print("\n[Step 3] Resuming graph with Approval...", flush=True)
    for event in graph.stream(Command(resume={"action": "approve"}), config=config):
        print(f"Resume event: {list(event.keys())}", flush=True)
        
    final_state = graph.get_state(config)
    print(f"Final Remediation Status: {final_state.values.get('remediation_status')}", flush=True)
    assert "Remediation executed" in final_state.values.get("remediation_status", ""), "Remediation should have executed!"
    
    print("\n=== TEST PASSED SUCCESSFULLY! ===", flush=True)

if __name__ == "__main__":
    test_graph_diagnosis_and_interrupt()
