"""Local practice demos for the email support graph.

Run: python demo.py

Uses the compiled app from graph.py. Does not define the workflow itself.
"""

from __future__ import annotations

import uuid

from langgraph.types import Command

from graph import get_sync_app, show_graph

app = get_sync_app()


def run_until_sent(initial_state: dict, thread_id: str) -> None:
    config = {"configurable": {"thread_id": thread_id}}
    result = app.invoke(initial_state, config)

    if result.get("draft_response"):
        print(f"Draft ready for review: {result['draft_response'][:60]}...")

    if "__interrupt__" in result:
        result = app.invoke(Command(resume={"approved": True}), config)

    print("Email sent successfully!")

RESTART_THREAD = "restart-demo"


def pause_for_review() -> None:
    config = {"configurable": {"thread_id": RESTART_THREAD}}
    result = app.invoke(
        {
            "email_content": "I was charged twice for my subscription! This is urgent!",
            "sender_email": "customer@example.com",
            "email_id": "email_restart",
        },
        config,
    )
    if "__interrupt__" in result:
        print(f"Paused at human_review. thread_id={RESTART_THREAD}")
        print("Stop this process, then run resume_after_restart in a new terminal.")
    else:
        print("No interrupt — check classification urgency/intent.")


def resume_after_restart() -> None:
    config = {"configurable": {"thread_id": RESTART_THREAD}}
    app.invoke(Command(resume={"approved": True}), config)
    print("Resumed after restart — reply sent.")

def main() -> None:
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


if __name__ == "__main__":
    main()
