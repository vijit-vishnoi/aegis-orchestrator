import os
import re
import asyncio
from typing import Literal, TypedDict, Annotated
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.types import interrupt, Command
from langchain_core.runnables import RunnableConfig
from slack_sdk import WebClient
from worker_nodes import fetch_container_logs, get_container_stats, call_mcp_tool

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
except ImportError:
    ChatGoogleGenerativeAI = None  # type: ignore

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    next_node: str | None
    remediation_status: str | None
    approval_dispatched: bool | None
    diagnosis_reasoning: str | None
    proposed_action: str | None
    target_container: str | None
    alert_summary: str | None

SUPERVISOR_SYSTEM_PROMPT = """You are the Aegis Incident Diagnostic Agent, an expert Site Reliability Engineer (SRE).

Your mission:
1. Analyze the incoming Alertmanager webhook alert to identify the problem and affected container.
2. Investigate the root cause using your diagnostic tools:
   - Call `fetch_container_logs(container_name, tail=50)` to inspect container logs for errors, deadlocks, exceptions, or connection pool exhaustion.
   - Call `get_container_stats(container_name)` to inspect live CPU and memory utilization.
3. Formulate an AI Diagnosis and propose a concrete Remediation Step (e.g. Restart container '<container_name>').

Operating Rules:
- Always run diagnostic tools before finalizing your remediation recommendation.
- CRITICAL: Your DIAGNOSIS must be under 3 sentences. Do NOT output raw error traces, base64 strings, or long stack signatures.
- When you are ready to conclude your investigation, do NOT call further tools. Provide your final response in this exact format:
ALERT: <Brief summary of the alert>
DIAGNOSIS: <Root cause explanation based on the diagnostic logs and stats>
PROPOSED_FIX: Restart container '<container_name>'
"""

def parse_llm_diagnosis(content: str | list, state: AgentState) -> tuple[str, str, str, str]:
    if isinstance(content, list):
        content = "".join(
            part["text"] if isinstance(part, dict) and "text" in part
            else part if isinstance(part, str)
            else getattr(part, "text", str(part))
            for part in content
        ).strip()

    target_container = state.get("target_container") or "target_app"
    alert_summary = state.get("alert_summary") or "Alert detected on infrastructure"
    
    diagnosis = ""
    proposed_action = f"Restart container '{target_container}'"
    
    for line in content.splitlines():
        line_clean = line.strip()
        if line_clean.upper().startswith("ALERT:"):
            alert_summary = line_clean.split(":", 1)[1].strip()
        elif line_clean.upper().startswith("DIAGNOSIS:"):
            diagnosis = line_clean.split(":", 1)[1].strip()
        elif line_clean.upper().startswith("PROPOSED_FIX:") or line_clean.upper().startswith("PROPOSED FIX:"):
            val = line_clean.split(":", 1)[1].strip()
            if val:
                proposed_action = val
                match = re.search(r"['\"]([a-zA-Z0-9_\-]+)['\"]", val)
                if match:
                    target_container = match.group(1)

    if not diagnosis:
        diagnosis = content.strip() if content.strip() else f"Anomalous behavior identified in container '{target_container}'."
        
    return diagnosis, proposed_action, alert_summary, target_container

def get_diagnostic_llm():
    if not os.environ.get("GOOGLE_API_KEY"):
        print("[Supervisor] WARNING: GOOGLE_API_KEY is missing from environment. Falling back to diagnostic tools.")
        return None

    if ChatGoogleGenerativeAI is None:
        print("[Supervisor] WARNING: 'langchain-google-genai' is not installed. Please run `pip install langchain-google-genai`. Falling back to diagnostic tools.")
        return None

    try:
        return ChatGoogleGenerativeAI(model="gemini-3.5-flash-lite")
    except Exception as e:
        print(f"[Supervisor] WARNING: Failed to instantiate ChatGoogleGenerativeAI: {e}. Falling back to diagnostic tools.")
        return None

def supervisor_node(state: AgentState) -> Command[Literal["diagnostic_tools", "dispatch_approval", "__end__"]]:
    print("--- SUPERVISOR NODE ---")
    
    if state.get("remediation_status"):
        print("Remediation already processed. Ending workflow.")
        return Command(
            update={"next_node": "__end__"},
            goto="__end__"
        )

    target_container = state.get("target_container")
    if not target_container:
        messages = state["messages"]
        last_msg = str(messages[-1].content) if messages else ""
        match = re.search(r"(?:target_app|[a-zA-Z0-9_\-]+(?:-service|-app|-container))", last_msg)
        target_container = match.group(0) if match else "target_app"
    
    alert_summary = state.get("alert_summary")
    if not alert_summary and state.get("messages"):
        alert_summary = str(state["messages"][0].content).split("\n")[0][:100]

    llm = get_diagnostic_llm()
    tools = [fetch_container_logs, get_container_stats]
    
    if llm is not None:
        try:
            llm_with_tools = llm.bind_tools(tools)
            conversation = [SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT)] + list(state["messages"])
            response = llm_with_tools.invoke(conversation)
            
            if getattr(response, "tool_calls", None):
                print(f"[Supervisor] LLM requested {len(response.tool_calls)} tool calls: {[tc['name'] for tc in response.tool_calls]}")
                return Command(
                    update={
                        "messages": [response],
                        "target_container": target_container,
                        "alert_summary": alert_summary,
                        "next_node": "diagnostic_tools"
                    },
                    goto="diagnostic_tools"
                )
            
            if isinstance(response.content, list):
                content = "".join(
                    part["text"] if isinstance(part, dict) and "text" in part
                    else part if isinstance(part, str)
                    else getattr(part, "text", str(part))
                    for part in response.content
                ).strip()
            elif isinstance(response.content, str):
                content = response.content.strip()
            else:
                content = str(response.content).strip()

            diagnosis, proposed_action, parsed_alert, parsed_container = parse_llm_diagnosis(content, state)
            
            print(f"[Supervisor] Diagnosis formulated: {diagnosis}")
            print(f"[Supervisor] Proposed action: {proposed_action}")
            
            return Command(
                update={
                    "messages": [response],
                    "diagnosis_reasoning": diagnosis,
                    "proposed_action": proposed_action,
                    "alert_summary": parsed_alert or alert_summary,
                    "target_container": parsed_container or target_container,
                    "next_node": "dispatch_approval"
                },
                goto="dispatch_approval"
            )
        except Exception as e:
            print(f"[Supervisor] LLM invocation encountered an issue ({e}). Proceeding with diagnostic tool inspection fallback.")

    print(f"[Supervisor] Executing direct diagnostic inspection on container '{target_container}'...")
    logs = fetch_container_logs.invoke({"container_name": target_container, "tail": 50})
    stats = get_container_stats.invoke({"container_name": target_container})
    
    diagnosis = (
        f"Automated diagnosis for container '{target_container}': "
        f"Metrics show abnormal load ({stats}). "
        f"Recent logs: {logs[-250:] if len(logs) > 250 else logs}."
    )
    proposed_action = f"Restart container '{target_container}'"
    
    return Command(
        update={
            "messages": [AIMessage(content=f"DIAGNOSIS: {diagnosis}\nPROPOSED_FIX: {proposed_action}")],
            "diagnosis_reasoning": diagnosis,
            "proposed_action": proposed_action,
            "alert_summary": alert_summary or f"Alert on {target_container}",
            "target_container": target_container,
            "next_node": "dispatch_approval"
        },
        goto="dispatch_approval"
    )

def dispatch_approval(state: AgentState, config: RunnableConfig) -> Command[Literal["execute_remediation"]]:
    print("--- DISPATCH APPROVAL NODE ---")
    thread_id = config.get("configurable", {}).get("thread_id", "unknown-thread")
    
    alert_summary = state.get("alert_summary") or "Alert detected on infrastructure"
    diagnosis = state.get("diagnosis_reasoning") or "AI identified abnormal behavior from container logs and metrics."
    if len(diagnosis) > 2500:
        diagnosis = diagnosis[:2500] + "..."
    proposed_action = state.get("proposed_action") or f"Restart container '{state.get('target_container', 'target_app')}'"
    
    slack_token = os.environ.get("SLACK_BOT_TOKEN")
    slack_channel = os.environ.get("SLACK_CHANNEL_ID", "#general")
    
    if slack_token:
        try:
            client = WebClient(token=slack_token)
            blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*Aegis Orchestrator Alert ({thread_id})*\n"
                            f"*Alert:* {alert_summary}\n"
                            f"*AI Diagnosis:* {diagnosis}\n"
                            f"*Proposed Fix:* {proposed_action}"
                        )
                    }
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
            client.chat_postMessage(
                channel=slack_channel,
                text=f"Remediation Approval Required: {proposed_action}",
                blocks=blocks
            )
            print(f"Dispatched Slack approval message to {slack_channel}")
        except Exception as e:
            print(f"Failed to send Slack message: {e}")
            
    return Command(
        update={"approval_dispatched": True},
        goto="execute_remediation"
    )

def execute_remediation(state: AgentState, config: RunnableConfig) -> Command[Literal["supervisor"]]:
    print("--- EXECUTE REMEDIATION NODE ---")
    proposed_action = state.get("proposed_action") or f"Restart container '{state.get('target_container', 'target_app')}'"
    target_container = state.get("target_container") or "target_app"
    diagnosis = state.get("diagnosis_reasoning") or "No detailed diagnosis provided"
    
    print(f"Pausing execution for approval of: {proposed_action}")
    
    human_approval = interrupt(
        {
            "action_required": True,
            "question": f"Do you approve the following action: {proposed_action}?",
            "proposed_action": proposed_action,
            "diagnosis": diagnosis,
            "target_container": target_container
        }
    )
    
    if human_approval == "approve" or (isinstance(human_approval, dict) and human_approval.get("action") == "approve"):
        print(f"Approval received. Executing remediation on '{target_container}'...")
        from worker_nodes import sync_call_mcp
        result = sync_call_mcp("execute_container_restart", {"container_name": target_container})
        status = f"Remediation executed successfully. MCP output: {result}"
    else:
        print("Remediation rejected by human.")
        status = "Remediation rejected by human."
        
    return Command(
        update={
            "messages": [HumanMessage(content=f"Remediation Node: {status}")],
            "remediation_status": status
        },
        goto="supervisor"
    )

def build_graph() -> StateGraph:
    from langgraph.prebuilt import ToolNode
    
    builder = StateGraph(AgentState)  # type: ignore
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("diagnostic_tools", ToolNode([fetch_container_logs, get_container_stats]))
    builder.add_node("dispatch_approval", dispatch_approval)
    builder.add_node("execute_remediation", execute_remediation)
    
    builder.add_edge(START, "supervisor")
    builder.add_edge("diagnostic_tools", "supervisor")
    
    return builder

def get_graph():
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg_pool import ConnectionPool
    
    db_uri = os.environ.get("DB_URI", "postgresql://postgres:postgrespassword@localhost:5432/aegis")
    pool = ConnectionPool(db_uri)
    # pyrefly: ignore[bad-argument-type]
    checkpointer = PostgresSaver(pool)
    checkpointer.setup()
    
    builder = build_graph()
    graph = builder.compile(checkpointer=checkpointer)
    return graph
