import uuid
import os
from typing import Literal, TypedDict
from IPython.display import Image,display
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.types import Command,interrupt
from langgraph.graph import StateGraph,START,END

load_dotenv()

#Define state schemas

class EmailClassification(TypedDict):
    intent : Literal["question","bug","billing","feature","complex"]
    urgency : Literal["low","medium","high","critical"]
    topic : str
    summary : str

class EmailAgentState(TypedDict):
    #raw email data
    email_content: str
    sender_email:str
    email_id:str

    #classifier result
    classification: EmailClassification | None

    #bug tracking
    ticket_id: str | None

    #raw search results
    search_results : list[str] | None
    customer_history : list[str] | None

    #generated response
    draft_response :  str | None

#Nodes

def read_email(state: EmailAgentState)->EmailAgentState:
    """Read the email content from the state"""
    pass

llm = ChatOpenAI(model="gpt-5-mini")

def classify_email(state: EmailAgentState)->EmailAgentState:
    """Classify the email into a category and route accordingly"""

    structured_llm=llm.with_structured_output(EmailClassification)

    classification_prompt = f"""
    Analyze this customer email and classify it:

    Email: {state['email_content']}
    From: {state['sender_email']}

    Provide classification, including intent, urgency, topic, and summary
    """

    classification=stuctured_llm.invoke(classification_prompt)

    return {"classification" : classification }

def search_documentation(state: EmailAgentState) -> EmailAgentState:
    """Search knowledge base for relevant information"""

    # Build search query from classification
    classification = state.get('classification', {})
    query = f"{classification.get('intent', '')} {classification.get('topic', '')}"

    try:
        # Implement search logic here
        search_results = [
            "--Search_result_1--",
            "--Search_result_2--",
            "--Search_result_3--"
        ]
    except SearchAPIError as e:
        # For recoverable search errors, store error and continue
        search_results = [f"Search temporarily unavailable: {str[e]}"]

    return {"search_results": search_results} # Raw search results or error

def bug_tracking(state: EmailAgentState)->EmailAgentState:

    #create ticket in your bug tracking system
    ticket_id =f"BUG_{uuid.uuid4()}"

    return {"ticket_id": ticket_id}

#conditional hence we return a command
def write_response(state: EmailAgentState) -> Command[Literal["human_review", "send_reply"]]:
    "Generate response using context and route based on quality"""

    classification = state.get('classification', {})

    # Format context from raw state data on demand|
    #creating a list of context sections
    context_sections = []

    if state.get('search_results'):
        # Format search results for the prompt
        formatted_docs = "\n".join([f"- {doc}" for doc in state['search_results']])
        context_sections.append(f"Relevant documentation:\n{formatted_docs}")

    if state.get('customer_history'):
        # Format customer data for the prompt
        context_sections.append(f"Customer tier: {state['customer_history'].get('tier', 'standard')}")

    # Build the prompt with formatted context
    draft_prompt = f"""
    Draft a response to this customer email:
    {state['email_content']}

    Email intent: {classification.get('intent', 'unkown')}
    Urgency level: {classification.get('urgency', 'medium')}

    {chr(10).join(context_sections)}

    Guidelines:
    - Be professional and helpful
    - Address their specific concern
    - Use the provided documentation when relevant
    - Be brief
    """

    response = llm.invoke(draft_prompt)

    # Determine if human review is needed based on urgency and intent
    needs_review = (
        classification.get('urgency') in ['high', 'critical'] or
        classification.get('intent') == 'complex'
    )

    # Route to the appropriate next node
    if needs_review:
        goto = "human_review"
        print("Needs approval")
    else:
        goto = "send_reply"

    return Command(
        update = {"draft_response": response.content},
        goto = goto
    )

def human_review(state: EmailAgentState) -> Command[Literal["send_reply", END]]:
    """Pause for human review using interrupt and route based on decision"""

    classification = state.get('classification', {})

    # Interrupt() must come first - any code before it will re-run on resume
    human_decision = interrupt({
        "email_id": state['email_id'],
        "original_email": state['email_content'],
        "draft_response": state.get('draft_response', ""),
        "urgency": classification.get('urgency'),
        "intent": classification.get('intent'),
        "action": "Please review and approve/edit this response"
    })

    # Now process the human's decision
    if human_decision.get("approved"):
        return Command(
            update = {"draft_response": human_decision.get("edited_response", state['draft_response'])},
            goto = "send_reply"
        )
    else:
        # Rejection means human will handle directly
        return Command(update = {}, goto = END)

def send_reply(state: EmailAgentState) -> EmailAgentState:
    """Send the email response"""
    # Integrate with a email service
    print(f"Sending reply: {state['draft_response'][:60]}...")
    return {}