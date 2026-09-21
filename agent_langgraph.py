"""
Autonomous Research Agent - LangGraph Version

This is the SAME logic as agent.py (plan -> draft -> critique -> revise),
just restructured as an explicit graph instead of plain Python function calls.

Why this matters: the critique/revise loop is now a real graph loop with a
conditional edge, not a hidden `for` loop inside a function. This is the
standard way production agent systems are built, and it's much easier to
explain and extend (e.g. add new nodes, change the loop condition) than a
plain script.

Setup:
    pip install langgraph google-genai tavily-python python-dotenv

.env file needs:
    GEMINI_API_KEY=your_key_here
    TAVILY_API_KEY=your_key_here

Run this with: python agent_langgraph.py
"""

import os
from typing import TypedDict, List, Dict
from dotenv import load_dotenv
from google import genai
from google.genai import types
from tavily import TavilyClient
from langgraph.graph import StateGraph, START, END

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
MODEL_NAME = "gemini-3.5-flash-lite"

web_search_function = {
    "name": "web_search",
    "description": "Search the web for current information on a topic or question.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query to look up"}
        },
        "required": ["query"]
    }
}
tools = types.Tool(function_declarations=[web_search_function])
config = types.GenerateContentConfig(tools=[tools])


# ============================================================
# STATE: the one shared dictionary that flows through the graph
# ============================================================
class ResearchState(TypedDict):
    topic: str
    plan: str
    sources: List[Dict]
    draft: str
    current_version: str
    critique: str
    round: int
    max_rounds: int
    final_report: str


# ============================================================
# HELPER FUNCTIONS (same as agent.py, unchanged)
# ============================================================
def run_search(query: str, sources: list) -> str:
    print(f"\n🔍 Agent is searching for: '{query}'")
    results = tavily.search(query=query, max_results=4)
    formatted = []
    for r in results.get("results", []):
        url = r["url"]
        existing = next((s for s in sources if s["url"] == url), None)
        if existing:
            source_id = existing["id"]
        else:
            source_id = len(sources) + 1
            sources.append({"id": source_id, "title": r["title"], "url": url})
        formatted.append(f"[{source_id}] {r['title']}: {r['content'][:300]}")
    return "\n".join(formatted) if formatted else "No results found."


def format_reference_list(sources: list) -> str:
    if not sources:
        return ""
    lines = [f"[{s['id']}] {s['title']} - {s['url']}" for s in sources]
    return "\n## References\n" + "\n".join(lines)


# ============================================================
# NODES: each function takes the current state and returns updates
# ============================================================
def plan_node(state: ResearchState) -> dict:
    print("🧭 Planning research...")
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=(
            f"I want to write a well-researched report on: '{state['topic']}'. "
            f"Before any research happens, break this topic down into 3-5 specific "
            f"sub-questions that, if answered, would let me write a thorough report. "
            f"Return ONLY a numbered list, nothing else."
        )
    )
    print("\n📋 Research plan:\n" + response.text)
    return {"plan": response.text}


def draft_node(state: ResearchState, max_turns: int = 6) -> dict:
    print("\n🔎 Gathering information and writing draft...")
    sources: List[Dict] = []

    contents = [
        types.Content(
            role="user",
            parts=[types.Part(text=(
                f"I need a well-researched report on: '{state['topic']}'. "
                f"Here is the research plan to follow:\n{state['plan']}\n\n"
                f"Use the web_search tool as many times as needed to answer each "
                f"sub-question in the plan before writing the final report. "
                f"Each search result will come back with a source ID like [1], [2]. "
                f"Cite claims using those exact IDs, e.g. 'AI adoption reached 80% [3].' "
                f"Do not invent citations. Write a clear, well-structured draft report "
                f"with a short intro, key findings with inline [n] citations, and a conclusion."
            ))]
        )
    ]

    draft_text = "⚠️ No draft produced."
    for _ in range(max_turns):
        response = client.models.generate_content(model=MODEL_NAME, contents=contents, config=config)
        candidate = response.candidates[0]
        function_calls = [p.function_call for p in candidate.content.parts if p.function_call is not None]
        contents.append(candidate.content)

        if not function_calls:
            draft_text = "".join(p.text for p in candidate.content.parts if p.text)
            break

        function_response_parts = []
        for fc in function_calls:
            if fc.name == "web_search":
                result_text = run_search(fc.args["query"], sources)
                function_response_parts.append(
                    types.Part.from_function_response(name="web_search", response={"result": result_text})
                )
        contents.append(types.Content(role="user", parts=function_response_parts))

    print("\n📄 Draft complete.")
    return {"draft": draft_text, "current_version": draft_text, "sources": sources, "round": 0}


def critique_node(state: ResearchState) -> dict:
    print(f"\n🔍 Critique round {state['round'] + 1} of {state['max_rounds']}...")
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=(
            f"Here is a draft research report on '{state['topic']}':\n\n{state['current_version']}\n\n"
            f"Critically review this draft. List specific weaknesses: claims made "
            f"WITHOUT a bracketed [n] citation, gaps in coverage, or unclear structure. "
            f"Be honest and specific, not generic."
        )
    )
    print("\n📝 Critique:\n" + response.text)
    return {"critique": response.text}


def revise_node(state: ResearchState) -> dict:
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=(
            f"Current draft report on '{state['topic']}':\n\n{state['current_version']}\n\n"
            f"Critique of that draft:\n\n{state['critique']}\n\n"
            f"Now write a final, improved version of the report that addresses this "
            f"critique. Keep all existing [n] citation tags exactly as they are. "
            f"Return ONLY the final report."
        )
    )
    return {"current_version": response.text, "round": state["round"] + 1}


def finalize_node(state: ResearchState) -> dict:
    final = state["current_version"] + "\n" + format_reference_list(state["sources"])
    return {"final_report": final}


# ============================================================
# CONDITIONAL EDGE: decides whether to loop back to critique or finish
# ============================================================
def should_continue_critiquing(state: ResearchState) -> str:
    if state["round"] < state["max_rounds"]:
        return "critique"   # loop back
    return "finalize"       # done looping


# ============================================================
# BUILD THE GRAPH
# ============================================================
graph = StateGraph(ResearchState)

graph.add_node("plan", plan_node)
graph.add_node("draft", draft_node)
graph.add_node("critique", critique_node)
graph.add_node("revise", revise_node)
graph.add_node("finalize", finalize_node)

graph.add_edge(START, "plan")
graph.add_edge("plan", "draft")
graph.add_edge("draft", "critique")
graph.add_edge("critique", "revise")

# This is the loop: after revising, either go back to critique or move on
graph.add_conditional_edges(
    "revise",
    should_continue_critiquing,
    {"critique": "critique", "finalize": "finalize"}
)

graph.add_edge("finalize", END)

app = graph.compile()


if __name__ == "__main__":
    topic = input("What topic do you want researched? ")

    initial_state: ResearchState = {
        "topic": topic,
        "plan": "",
        "sources": [],
        "draft": "",
        "current_version": "",
        "critique": "",
        "round": 0,
        "max_rounds": 2,
        "final_report": ""
    }

    result = app.invoke(initial_state)

    print("\n" + "=" * 60)
    print("FINAL REPORT")
    print("=" * 60)
    print(result["final_report"])

    with open("report.md", "w", encoding="utf-8") as f:
        f.write(result["final_report"])
    print("\n✅ Report also saved to report.md")