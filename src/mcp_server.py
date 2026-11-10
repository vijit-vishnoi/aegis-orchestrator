"""MCP Server Entrypoint exposing infrastructure diagnostics and remediation tools."""
import sys
import os

# Ensure tools module is discoverable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tools.mcp_server import mcp, fetch_container_logs, get_container_stats, execute_container_restart, get_cpu_metrics, get_error_logs

if __name__ == "__main__":
    mcp.run()

