import os
import logging
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from dotenv import load_dotenv
from langgraph.types import Command
from main import get_graph

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = App(token=os.environ.get("SLACK_BOT_TOKEN"))

def send_approval_message(channel_id: str, thread_id: str, question: str):
    app.client.chat_postMessage(
        channel=channel_id,
        text="Remediation Approval Required",
        blocks=[
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Aegis Orchestrator Alert ({thread_id})*\n{question}"}
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
def handle_approve_action(ack, body, logger):
    ack()
    user = body["user"]["id"]
    thread_id = body["actions"][0]["value"]
    logger.info(f"User {user} approved remediation for thread {thread_id}")
    
    graph = get_graph()
    thread_config = {"configurable": {"thread_id": thread_id}}
    
    logger.info("Resuming LangGraph execution with Approval...")
    for event in graph.stream(Command(resume="approve"), config=thread_config):
        pass
        
    response_url = body["response_url"]
    app.client.chat_update(
        channel=body["container"]["channel_id"],
        ts=body["container"]["message_ts"],
        text="Remediation Approved and Executed ✅",
        blocks=[]
    )

@app.action("reject_remediation")
def handle_reject_action(ack, body, logger):
    ack()
    user = body["user"]["id"]
    thread_id = body["actions"][0]["value"]
    logger.info(f"User {user} rejected remediation for thread {thread_id}")
    
    graph = get_graph()
    thread_config = {"configurable": {"thread_id": thread_id}}
    
    logger.info("Resuming LangGraph execution with Rejection...")
    for event in graph.stream(Command(resume="reject"), config=thread_config):
        pass

    app.client.chat_update(
        channel=body["container"]["channel_id"],
        ts=body["container"]["message_ts"],
        text="Remediation Rejected ❌",
        blocks=[] 
    )

if __name__ == "__main__":
    app_token = os.environ.get("SLACK_APP_TOKEN")
    
    if not app_token or not os.environ.get("SLACK_BOT_TOKEN"):
        logger.warning("SLACK_APP_TOKEN or SLACK_BOT_TOKEN not found in .env file.")
        logger.warning("Please set them to connect to Slack.")
    else:
        print("Starting Slack Socket Mode Handler...")
        handler = SocketModeHandler(app, app_token)
        handler.start()
