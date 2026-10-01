import sqlite3
import os
from typing import Literal, TypedDict, Annotated
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.types import interrupt, Command
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from slack_sdk import WebClient

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    next_node: str | None
    remediation_status: str | None
    approval_dispatched: bool | None

def supervisor_node(state: AgentState) -> Command[Literal["metric_explorer", "log_analyzer", "dispatch_approval", "__end__"]]:
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
        goto = "dispatch_approval"
    else:
        goto = "__end__"
        
    print(f"Routing to: {goto}")
    return Command(
        update={"next_node": goto},
        goto=goto
    )

def dispatch_approval(state: AgentState, config: RunnableConfig) -> Command[Literal["execute_remediation"]]:
    print("--- DISPATCH APPROVAL NODE ---")
    proposed_action = "Restart pod 'api-server' in namespace 'prod'"
    
                                                                  
    slack_token = os.environ.get("SLACK_BOT_TOKEN")
    slack_channel = os.environ.get("SLACK_CHANNEL_ID", "#general")
    thread_id = config.get("configurable", {}).get("thread_id", "unknown-thread")
    
    if slack_token:
        try:
            client = WebClient(token=slack_token)
            blocks = [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Aegis Orchestrator Alert ({thread_id})*\nDo you approve the following action:\n_{proposed_action}_"}
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Approve"},
                            "style": "primary",
                            "action_id": "approve_remediation",
                            "value": thread_id
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Reject"},
                            "style": "danger",
                            "action_id": "reject_remediation",
                            "value": thread_id
                        }
                    ]
                }
            ]
            client.chat_postMessage(channel=slack_channel, text="Remediation Approval Required", blocks=blocks)
            print(f"Dispatched Slack approval message to {slack_channel}")
        except Exception as e:
            print(f"Failed to send Slack message: {e}")
            
    return Command(
        update={"approval_dispatched": True},
        goto="execute_remediation"
    )

def execute_remediation(state: AgentState, config: RunnableConfig) -> Command[Literal["supervisor"]]:
    print("--- EXECUTE REMEDIATION NODE ---")
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
    
    builder = StateGraph(AgentState)                
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("metric_explorer", metric_explorer_node)
    builder.add_node("log_analyzer", log_analyzer_node)
    builder.add_node("dispatch_approval", dispatch_approval)
    builder.add_node("execute_remediation", execute_remediation)
    builder.add_edge(START, "supervisor")
    
    return builder

def get_graph():
    conn = sqlite3.connect("aegis_checkpoints.sqlite", check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    builder = build_graph()
    graph = builder.compile(checkpointer=checkpointer)
    return graph
