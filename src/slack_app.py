import sys
import asyncio
import warnings

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore
import os
from dotenv import load_dotenv
load_dotenv()
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from langgraph.types import Command
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from main import get_graph
app = AsyncApp(token=os.environ.get("SLACK_BOT_TOKEN"))

DB_URI = os.environ.get("DB_URI", "postgresql://postgres:postgrespassword@localhost:5432/aegis")

async def send_remediation_approval_message(channel_id: str, thread_id: str, proposed_action: str):
    """
    Helper function called by the LangGraph remediation node to send the interactive Block Kit message.
    """
    await app.client.chat_postMessage(
        channel=channel_id,
        text="Remediation Approval Required",
        blocks=[
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
    )

@app.action("approve_remediation")
async def handle_approve_remediation(ack, body, client):
    await ack()
    
    try:
        thread_id = body["actions"][0]["value"]
        channel_id = body["channel"]["id"]
        message_ts = body["message"]["ts"]
        
        await client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text="Approved and Executing...",
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Aegis Orchestrator Alert ({thread_id})*\n:white_check_mark: *Approved and Executing...*"}
                }
            ]
        )
        
        print(f"[SlackApp] Resuming LangGraph thread: {thread_id}")
        graph = get_graph()
        thread_config = {"configurable": {"thread_id": thread_id}}
        resume_command = Command(resume={"action": "approve"})
        
        await asyncio.to_thread(graph.invoke, resume_command, thread_config)
    except Exception as e:
        print(f"[SlackApp] Error during graph resumption: {e}")

@app.action("reject_remediation")
async def handle_reject_remediation(ack, body, client):
    await ack()
    
    try:
        thread_id = body["actions"][0]["value"]
        channel_id = body["channel"]["id"]
        message_ts = body["message"]["ts"]
        
        await client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text="Remediation rejected by user. Aborting.",
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Aegis Orchestrator Alert ({thread_id})*\n:x: *Remediation rejected by user. Aborting.*"}
                }
            ]
        )
        
        print(f"[SlackApp] Resuming LangGraph thread: {thread_id} (Rejected)")
        graph = get_graph()
        thread_config = {"configurable": {"thread_id": thread_id}}
        resume_command = Command(resume={"action": "reject"})
        
        await asyncio.to_thread(graph.invoke, resume_command, thread_config)
    except Exception as e:
        print(f"[SlackApp] Error during graph resumption: {e}")

async def main():
    handler = AsyncSocketModeHandler(app, os.environ.get("SLACK_APP_TOKEN"))
    print("[SlackApp] Starting Slack Socket Mode listener...")
    await handler.start_async()

if __name__ == "__main__":
    asyncio.run(main())
