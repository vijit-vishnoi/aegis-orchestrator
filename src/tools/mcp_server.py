from fastmcp import FastMCP

mcp = FastMCP("Aegis Infrastructure APIs")

@mcp.tool()
def get_pod_metrics(namespace: str, pod_name: str) -> str:
    return f"CPU: 80%, Memory: 512Mi for {namespace}/{pod_name}"

@mcp.tool()
def get_pod_logs(namespace: str, pod_name: str, tail: int = 100) -> str:
    return f"Log data for {namespace}/{pod_name}: OOMKilled"

@mcp.tool()
def restart_pod(namespace: str, pod_name: str) -> str:
    return f"Pod {namespace}/{pod_name} restarted successfully."

if __name__ == "__main__":
    mcp.run()
