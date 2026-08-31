import sys
from pathlib import Path

# This file is named email.py, which would shadow Python's stdlib `email` package.
_script_dir = Path(__file__).resolve().parent
sys.path = [p for p in sys.path if p and Path(p).resolve() != _script_dir]

import os
import uuid
from typing import Literal, TypedDict
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.types import Command, interrupt
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver

load_dotenv()

# Define state schemas

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

# Nodes

def read_email(state: EmailAgentState) -> EmailAgentState:
    """Read the email content from the state"""
    print(f"Reading email {state['email_id']} from {state['sender_email']}")
    return {}

llm = ChatOpenAI(model="gpt-5-mini")

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
        context_sections.append(f"Customer tier: {state['customer_history'].get('tier', 'standard')}")

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
        classification.get("urgency") in ["high", "critical"] or
        classification.get("intent") == "complex"
    )

    if needs_review:
        goto = "human_review"
        print("Needs approval")
    else:
        goto = "send_reply"

    return Command(
        update={"draft_response": response.content},
        goto=goto
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
        "action": "Please review and approve/edit this response"
    })

    if human_decision.get("approved"):
        return Command(
            update={"draft_response": human_decision.get("edited_response", state["draft_response"])},
            goto="send_reply"
        )
    else:
        return Command(update={}, goto=END)

def send_reply(state: EmailAgentState) -> EmailAgentState:
    """Send the email response"""
    print(f"Sending reply: {state['draft_response'][:60]}...")
    return {}


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

memory = InMemorySaver()
app = builder.compile(checkpointer=memory)


def show_graph() -> None:
    """Save the compiled graph as a PNG and open it (Jupyter display does not work in a terminal)."""
    graph_path = _script_dir / "email_graph.png"
    graph_path.write_bytes(app.get_graph().draw_mermaid_png())
    print(f"Graph saved to {graph_path}")
    os.startfile(graph_path)


def run_until_sent(initial_state: dict, thread_id: str) -> None:
    config = {"configurable": {"thread_id": thread_id}}
    result = app.invoke(initial_state, config)

    if result.get("draft_response"):
        print(f"Draft ready for review: {result['draft_response'][:60]}...")

    if "__interrupt__" in result:
        result = app.invoke(Command(resume={"approved": True}), config)

    print("Email sent successfully!")


if __name__ == "__main__":
    show_graph()

    # Test with urgent billing issue
    run_until_sent(
        {
            "email_content": "I was charged twice for my subscription! This is urgent!",
            "sender_email": "customer@example.com",
            "email_id": "email_123",
        },
        thread_id="customer_123",
    )

    email_content = [
        "I was charged two times for my subscription! This is urgent!",
        "I was wondering if this was available in blue?",
        "Can you tell me how long the sale is on?",
        "The tire won't stay on the car!",
        "My subscription is going to end in a few months, what is the new rate?",
    ]
    needs_approval = []

    for i, content in enumerate(email_content):
        initial_state = {
            "email_content": content,
            "sender_email": "customer@example.com",
            "email_id": f"email_{i}",
        }
        print(f"{initial_state['email_id']}: ", end="", flush=True)

        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}
        result = app.invoke(initial_state, config)
        if "__interrupt__" in result:
            result["thread_id"] = thread_id
            needs_approval.append(result)
            print()

    print(f"\n{len(needs_approval)} email(s) waiting for approval. Auto-approving...")
    for pending in needs_approval:
        config = {"configurable": {"thread_id": pending["thread_id"]}}
        app.invoke(Command(resume={"approved": True}), config)

    print("Done.")