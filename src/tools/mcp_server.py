from fastmcp import FastMCP

mcp = FastMCP("Aegis Infrastructure APIs")

@mcp.tool()
def get_cpu_metrics(pod_name: str, duration_mins: int) -> str:
    return f"CPU: 95% over the last {duration_mins} mins for {pod_name}"

@mcp.tool()
def get_error_logs(service_name: str, time_window_mins: int) -> str:
    return f"[ERROR] OOMKilled in {service_name} within last {time_window_mins} mins."

@mcp.tool()
def execute_pod_restart(pod_name: str, namespace: str) -> str:
    return f"Pod {namespace}/{pod_name} restarted successfully."

if __name__ == "__main__":
    mcp.run()
