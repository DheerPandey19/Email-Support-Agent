"""Email support LangGraph: state, nodes, edges, and compiled app.

This module is the recipe only. Run demos via demo.py. HTTP comes later in server.py.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Literal, TypedDict

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

load_dotenv()

_SCRIPT_DIR = Path(__file__).resolve().parent

# --- State schemas ---


class EmailClassification(TypedDict):
    intent: Literal["question", "bug", "billing", "feature", "complex"]
    urgency: Literal["low", "medium", "high", "critical"]
    topic: str
    summary: str


class EmailAgentState(TypedDict):
    # raw email data
    email_content: str
    sender_email: str
    email_id: str

    # classifier result
    classification: EmailClassification | None

    # bug tracking
    ticket_id: str | None

    # raw search results
    search_results: list[str] | None
    customer_history: dict | None

    # generated response
    draft_response: str | None


# --- Nodes ---

llm = ChatOpenAI(model="gpt-5-mini")


def read_email(state: EmailAgentState) -> EmailAgentState:
    """Read the email content from the state"""
    print(f"Reading email {state['email_id']} from {state['sender_email']}")
    return {}


def classify_intent(state: EmailAgentState) -> EmailAgentState:
    """Classify the email into a category and route accordingly"""

    structured_llm = llm.with_structured_output(EmailClassification)

    classification_prompt = f"""
    Analyze this customer email and classify it:

    Email: {state['email_content']}
    From: {state['sender_email']}

    Provide classification, including intent, urgency, topic, and summary
    """

    classification = structured_llm.invoke(classification_prompt)

    return {"classification": classification}


def search_documentation(state: EmailAgentState) -> EmailAgentState:
    """Search knowledge base for relevant information"""

    classification = state.get("classification") or {}
    query = f"{classification.get('intent', '')} {classification.get('topic', '')}"

    search_results = [
        f"Documentation matching: {query.strip() or 'general support'}",
        "--Search_result_2--",
        "--Search_result_3--",
    ]

    return {"search_results": search_results}


def bug_tracking(state: EmailAgentState) -> EmailAgentState:
    ticket_id = f"BUG_{uuid.uuid4()}"
    return {"ticket_id": ticket_id}


def write_response(state: EmailAgentState) -> Command[Literal["human_review", "send_reply"]]:
    """Generate response using context and route based on quality"""

    classification = state.get("classification") or {}

    context_sections = []

    if state.get("search_results"):
        formatted_docs = "\n".join([f"- {doc}" for doc in state["search_results"]])
        context_sections.append(f"Relevant documentation:\n{formatted_docs}")

    if state.get("customer_history"):
        context_sections.append(
            f"Customer tier: {state['customer_history'].get('tier', 'standard')}"
        )

    draft_prompt = f"""
    Draft a response to this customer email:
    {state['email_content']}

    Email intent: {classification.get('intent', 'unknown')}
    Urgency level: {classification.get('urgency', 'medium')}

    {chr(10).join(context_sections)}

    Guidelines:
    - Be professional and helpful
    - Address their specific concern
    - Use the provided documentation when relevant
    - Be brief
    """

    response = llm.invoke(draft_prompt)

    needs_review = (
        classification.get("urgency") in ["high", "critical"]
        or classification.get("intent") == "complex"
    )

    if needs_review:
        goto = "human_review"
        print("Needs approval")
    else:
        goto = "send_reply"

    return Command(
        update={"draft_response": response.content},
        goto=goto,
    )


def human_review(state: EmailAgentState) -> Command[Literal["send_reply", END]]:
    """Pause for human review using interrupt and route based on decision"""

    classification = state.get("classification") or {}

    human_decision = interrupt({
        "email_id": state["email_id"],
        "original_email": state["email_content"],
        "draft_response": state.get("draft_response", ""),
        "urgency": classification.get("urgency"),
        "intent": classification.get("intent"),
        "action": "Please review and approve/edit this response",
    })

    if human_decision.get("approved"):
        return Command(
            update={
                "draft_response": human_decision.get(
                    "edited_response", state["draft_response"]
                )
            },
            goto="send_reply",
        )
    return Command(update={}, goto=END)


def send_reply(state: EmailAgentState) -> EmailAgentState:
    """Send the email response"""
    print(f"Sending reply: {state['draft_response'][:60]}...")
    return {}


# --- Graph build + compile ---

builder = StateGraph(EmailAgentState)

builder.add_node("read_email", read_email)
builder.add_node("classify_intent", classify_intent)
builder.add_node("search_documentation", search_documentation)
builder.add_node("bug_tracking", bug_tracking)
builder.add_node("write_response", write_response)
builder.add_node("human_review", human_review)
builder.add_node("send_reply", send_reply)

builder.add_edge(START, "read_email")
builder.add_edge("read_email", "classify_intent")
builder.add_edge("classify_intent", "search_documentation")
builder.add_edge("classify_intent", "bug_tracking")
builder.add_edge("search_documentation", "write_response")
builder.add_edge("bug_tracking", "write_response")
builder.add_edge("send_reply", END)

# DB_URI = os.environ["DATABASE_URL"]
# _pool = ConnectionPool(
#     conninfo=DB_URI,
#     kwargs={"autocommit": True, "prepare_threshold": 0},
#     open=True,
# )
# checkpointer = PostgresSaver(_pool)
# checkpointer.setup()  # creates tables the first time; safe to call again
# app = builder.compile(checkpointer=checkpointer)


def build_app(checkpointer):
    """Compile the email graph with the given checkpointer."""
    return builder.compile(checkpointer=checkpointer)

_sync_app=None

def get_sync_app():
    """Lazy sync Postgres compile for demo.py / CLI. Do not use from async server request path."""
    global _sync_app
    if _sync_app is not None:
        return _sync_app

    db_uri = os.environ["DATABASE_URL"]
    pool = ConnectionPool(
        conninfo=db_uri,
        kwargs={"autocommit": True, "prepare_threshold": 0},
        open=True,
    )
    checkpointer = PostgresSaver(pool)
    checkpointer.setup()
    _sync_app = build_app(checkpointer)
    return _sync_app



def show_graph() -> None:
    """Save the compiled graph as a PNG and open it."""
    graph_path = _SCRIPT_DIR / "email_graph.png"
    compiled = builder.compile()
    graph_path.write_bytes(compiled.get_graph().draw_mermaid_png())
    print(f"Graph saved to {graph_path}")
    os.startfile(graph_path)


if __name__ == "__main__":
    show_graph()
