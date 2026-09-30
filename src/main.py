import sqlite3
from typing import Literal, TypedDict, Annotated
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.types import interrupt, Command
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_core.messages import HumanMessage

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    next_node: str | None
    remediation_status: str | None

def supervisor_node(state: AgentState) -> Command[Literal["metric_explorer", "log_analyzer", "remediation", "__end__"]]:
    print("--- SUPERVISOR NODE ---")
    
    if state.get("remediation_status"):
        print("Remediation already processed. Ending workflow.")
        return Command(
            update={"next_node": "__end__"},
            goto="__end__"
        )
        
    messages = state["messages"]
    content = messages[-1].content
    last_msg = content.lower() if isinstance(content, str) else str(content).lower()
    
    if "metric" in last_msg:
        goto = "metric_explorer"
    elif "log" in last_msg:
        goto = "log_analyzer"
    elif "remediate" in last_msg or "fix" in last_msg or "restart" in last_msg:
        goto = "remediation"
    else:
        goto = "__end__"
        
    print(f"Routing to: {goto}")
    return Command(
        update={"next_node": goto},
        goto=goto
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
    
    if human_approval == "approve" or (isinstance(human_approval, dict) and human_approval.get("action") == "approve"):
        print("Approval received. Executing remediation...")
        import asyncio
        from worker_nodes import call_mcp_tool
        result = asyncio.run(call_mcp_tool("execute_pod_restart", {"pod_name": "api-server", "namespace": "prod"}))
        status = f"Remediation executed successfully. MCP output: {result}"
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
    from worker_nodes import metric_explorer_node, log_analyzer_node
    
    builder = StateGraph(AgentState)  # type: ignore
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
