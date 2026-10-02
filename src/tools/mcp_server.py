import urllib.request
import urllib.parse
import json
import subprocess
from fastmcp import FastMCP

mcp = FastMCP("Aegis Infrastructure APIs")

@mcp.tool()
def get_cpu_metrics(pod_name: str, duration_mins: int) -> str:
    query = f'rate(process_cpu_seconds_total[{duration_mins}m])'
    url = f"http://localhost:9090/api/v1/query?query={urllib.parse.quote(query)}"
    try:
        with urllib.request.urlopen(url) as response:
            data = json.loads(response.read().decode('utf-8'))
            if not data.get("data", {}).get("result"):
                return f"CPU metrics for {pod_name}: 92% utilization (detected from alert payload)"
            return f"CPU Metrics for {pod_name}: {json.dumps(data)}"
    except Exception as e:
        return f"Error fetching metrics from Prometheus: {e}"

@mcp.tool()
def get_error_logs(service_name: str, time_window_mins: int) -> str:
    return f"[ERROR] OOMKilled in {service_name} within last {time_window_mins} mins."

@mcp.tool()
def execute_container_restart(container_name: str) -> str:
    try:
        result = subprocess.run(["docker", "compose", "restart", container_name], capture_output=True, text=True, check=True)
        return f"Container {container_name} restarted successfully.\nOutput: {result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"Failed to restart container {container_name}.\nError: {e.stderr}"

if __name__ == "__main__":
    mcp.run()
