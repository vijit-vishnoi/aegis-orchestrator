import sys
import os
import asyncio
import concurrent.futures
from typing import Literal
from langgraph.types import Command
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

async def call_mcp_tool(tool_name: str, arguments: dict, timeout_seconds: int = 15) -> str:
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        if current_dir not in sys.path:
            sys.path.insert(0, current_dir)
        import tools.mcp_server as mcp_server
        if hasattr(mcp_server, tool_name):
            func = getattr(mcp_server, tool_name)
            if asyncio.iscoroutinefunction(func):
                return await func(**arguments)
            return func(**arguments)
    except Exception as e:
        print(f"[DEBUG] Direct FastMCP dispatch skipped: {e}")

    server_path = os.path.join(os.path.dirname(__file__), "tools", "mcp_server.py")
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-u", server_path],
        env=dict(os.environ, PYTHONUNBUFFERED="1")
    )
    
    print(f"[DEBUG] Starting MCP client for tool '{tool_name}'...")
    
    async def _call():
        async with stdio_client(server_params) as (read, write):
            print(f"[DEBUG] MCP stdio client connected.")
            async with ClientSession(read, write) as session:
                print(f"[DEBUG] Initializing MCP session...")
                await session.initialize()
                print(f"[DEBUG] Calling tool '{tool_name}' with args {arguments}...")
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

def sync_call_mcp(tool_name: str, arguments: dict) -> str:
    """Helper to execute MCP tools synchronously and reliably."""
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        if current_dir not in sys.path:
            sys.path.insert(0, current_dir)
        import tools.mcp_server as mcp_server
        if hasattr(mcp_server, tool_name):
            func = getattr(mcp_server, tool_name)
            if not asyncio.iscoroutinefunction(func):
                return func(**arguments)
    except Exception as e:
        pass

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
        
    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, call_mcp_tool(tool_name, arguments)).result()
    return asyncio.run(call_mcp_tool(tool_name, arguments))

@tool
def fetch_container_logs(container_name: str, tail: int = 50) -> str:
    """Retrieves the last N lines of logs for a specified Docker container to diagnose errors, crashes, and exceptions."""
    return sync_call_mcp("fetch_container_logs", {"container_name": container_name, "tail": tail})

@tool
def get_container_stats(container_name: str) -> str:
    """Retrieves current CPU and Memory usage statistics for a specified Docker container."""
    return sync_call_mcp("get_container_stats", {"container_name": container_name})

async def fetch_container_logs_node(state) -> Command[Literal["supervisor"]]:
    target = state.get("target_container") or "target_app"
    result = await call_mcp_tool("fetch_container_logs", {"container_name": target, "tail": 50})
    return Command(
        update={"messages": [HumanMessage(content=f"Container Logs for {target}:\n{result}")]},
        goto="supervisor"
    )

async def container_stats_node(state) -> Command[Literal["supervisor"]]:
    target = state.get("target_container") or "target_app"
    result = await call_mcp_tool("get_container_stats", {"container_name": target})
    return Command(
        update={"messages": [HumanMessage(content=f"Container Stats for {target}:\n{result}")]},
        goto="supervisor"
    )

async def metric_explorer_node(state) -> Command[Literal["supervisor"]]:
    result = await call_mcp_tool("get_cpu_metrics", {"pod_name": "target_app", "duration_mins": 1})
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
    from knowledge_base import search_postmortems
    messages = state["messages"]
    last_msg = messages[-1].content.lower()
    results = search_postmortems(last_msg)
    response = "\n".join(results)
    return Command(
        update={"messages": [HumanMessage(content=f"Postmortem Analyzer found:\n{response}")]},
        goto="supervisor"
    )
