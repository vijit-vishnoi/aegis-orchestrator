import sqlite3
from typing import Annotated, Literal, Sequence, TypedDict
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.types import interrupt, Command
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_ollama import ChatOllama
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

class AgentState(MessagesState):
    next_node: str | None
    remediation_status: str | None

llm = ChatOllama(model="llama3", temperature=0)

def supervisor_node(state: AgentState) -> Command[Literal["metric_explorer", "log_analyzer", "remediation", "__end__"]]:
    print("--- SUPERVISOR NODE ---")
    messages = state["messages"]
    last_msg = messages[-1].content.lower()
    
    if "metric" in last_msg:
        goto = "metric_explorer"
    elif "log" in last_msg:
        goto = "log_analyzer"
    elif "remediate" in last_msg or "fix" in last_msg:
        goto = "remediation"
    else:
        goto = "__end__"
        
    print(f"Routing to: {goto}")
    return Command(
        update={"next_node": goto},
        goto=goto
    )

def metric_explorer_node(state: AgentState) -> Command[Literal["supervisor"]]:
    print("--- METRIC EXPLORER WORKER ---")
    return Command(
        update={"messages": [HumanMessage(content="Metric Explorer: Analyzed metrics. CPU is at 99%.")]},
        goto="supervisor"
    )

def log_analyzer_node(state: AgentState) -> Command[Literal["supervisor"]]:
    print("--- LOG ANALYZER WORKER ---")
    return Command(
        update={"messages": [HumanMessage(content="Log Analyzer: Found OOM kill in logs.")]},
        goto="supervisor"
    )

def remediation_node(state: AgentState) -> Command[Literal["supervisor"]]:
    print("--- REMEDIATION NODE ---")
    proposed_action = "Restart pod 'api-server' in namespace 'prod'"
    
    print(f"Pausing execution for approval of: {proposed_action}")
    
    human_approval = interrupt(
        {
            "action_required": True,
            "question": f"Do you approve the following action: {proposed_action}?",
            "proposed_action": proposed_action
        }
    )
    
    if human_approval == "approve":
        print("Approval received. Executing remediation...")
        status = "Remediation executed successfully."
    else:
        print("Remediation rejected.")
        status = "Remediation rejected by human."
        
    return Command(
        update={
            "messages": [HumanMessage(content=f"Remediation Node: {status}")],
            "remediation_status": status
        },
        goto="supervisor"
    )

def build_graph() -> StateGraph:
    builder = StateGraph(AgentState)
    
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("metric_explorer", metric_explorer_node)
    builder.add_node("log_analyzer", log_analyzer_node)
    builder.add_node("remediation", remediation_node)
    
    builder.add_edge(START, "supervisor")
    
    return builder

def get_graph():
    conn = sqlite3.connect("aegis_checkpoints.sqlite", check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    
    builder = build_graph()
    graph = builder.compile(checkpointer=checkpointer)
    return graph

if __name__ == "__main__":
    graph = get_graph()
    thread_config = {"configurable": {"thread_id": "incident-001"}}
    
    print("Starting Aegis Investigation...")
    initial_input = {"messages": [HumanMessage(content="We have an alert: Fix the API server.")]}
    
    for event in graph.stream(initial_input, config=thread_config):
        pass
        
    state = graph.get_state(thread_config)
    if state.next and state.tasks and state.tasks[0].interrupts:
        print("\n=== GRAPH PAUSED ===")
        interrupt_val = state.tasks[0].interrupts[0].value
        print(f"Waiting for approval: {interrupt_val}")
        print("Run `python src/slack_handler.py` to approve or reject via Slack.")
