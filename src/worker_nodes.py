import sys
import os
import asyncio
from typing import Literal
from langgraph.types import Command
from langchain_core.messages import HumanMessage
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters
from knowledge_base import search_postmortems

async def call_mcp_tool(tool_name: str, arguments: dict, timeout_seconds: int = 15) -> str:
    server_path = os.path.join(os.path.dirname(__file__), "tools", "mcp_server.py")
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[server_path],
        env=os.environ.copy()
    )
    
    print(f"[DEBUG] Starting MCP client for tool '{tool_name}'...")
    
    async def _call():
        async with stdio_client(server_params) as (read, write):
            print(f"[DEBUG] MCP stdio client connected.")
            async with ClientSession(read, write) as session:
                print(f"[DEBUG] Initializing MCP session...")
                await session.initialize()
                print(f"[DEBUG] Calling tool '{tool_name}'...")
                result = await session.call_tool(tool_name, arguments)
                print(f"[DEBUG] MCP Tool call completed.")
                return result.content[0].text  # type: ignore

    try:
        return await asyncio.wait_for(_call(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        print(f"[ERROR] MCP Tool '{tool_name}' timed out after {timeout_seconds} seconds.")
        return f"Error: Timeout calling {tool_name}"
    except Exception as e:
        print(f"[ERROR] MCP Tool '{tool_name}' failed: {e}")
        return f"Error: {str(e)}"

async def metric_explorer_node(state) -> Command[Literal["supervisor"]]:
    result = await call_mcp_tool("get_cpu_metrics", {"pod_name": "api-server", "duration_mins": 15})
    # Avoid using 'metric' in the response so the supervisor doesn't loop back to us.
    return Command(
        update={"messages": [HumanMessage(content=f"CPU Analysis: {result}. Recommend fix.")]},
        goto="supervisor"
    )

async def log_analyzer_node(state) -> Command[Literal["supervisor"]]:
    result = await call_mcp_tool("get_error_logs", {"service_name": "api-server", "time_window_mins": 30})
    return Command(
        update={"messages": [HumanMessage(content=f"Log Analysis: {result}")]},
        goto="supervisor"
    )

def postmortem_analyzer_node(state) -> Command[Literal["supervisor"]]:
    messages = state["messages"]
    last_msg = messages[-1].content.lower()
    results = search_postmortems(last_msg)
    response = "\n".join(results)
    return Command(
        update={"messages": [HumanMessage(content=f"Postmortem Analyzer found:\n{response}")]},
        goto="supervisor"
    )
