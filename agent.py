"""
Autonomous Research Agent - Starter Version (Gemini API)

What this does:
- You give it a topic
- The model decides WHEN and WHAT to search for (this is the "agentic" part -
  you are not hardcoding the search query, the model chooses it)
- It can call the search tool multiple times if it needs more info
- Once it has enough, it writes a short report

Setup:
    pip install google-genai tavily-python python-dotenv

.env file needs:
    GEMINI_API_KEY=your_key_here
    TAVILY_API_KEY=your_key_here

Run this with: python agent.py
"""

import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
from tavily import TavilyClient

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

# Gemini Flash-Lite models have the most generous free daily quota.
# Swap to "gemini-3.5-flash" if you want a stronger model and don't mind fewer free calls/day.
MODEL_NAME = "gemini-3.5-flash-lite"


# --- Define the tool the model is allowed to use ---
web_search_function = {
    "name": "web_search",
    "description": "Search the web for current information on a topic or question.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to look up"
            }
        },
        "required": ["query"]
    }
}

tools = types.Tool(function_declarations=[web_search_function])
config = types.GenerateContentConfig(tools=[tools])


def run_search(query: str, sources: list) -> str:
    """
    Calls Tavily and returns results with explicit numbered source IDs like [1], [2].
    The `sources` list is shared across the whole research run, so the same URL
    always gets the same ID, and we end up with one clean reference list at the end.
    """
    print(f"\n🔍 Agent is searching for: '{query}'")
    results = tavily.search(query=query, max_results=4)
    formatted = []
    for r in results.get("results", []):
        url = r["url"]
        # Reuse the ID if we've already seen this URL, otherwise add it as new
        existing = next((s for s in sources if s["url"] == url), None)
        if existing:
            source_id = existing["id"]
        else:
            source_id = len(sources) + 1
            sources.append({"id": source_id, "title": r["title"], "url": url})
        formatted.append(f"[{source_id}] {r['title']}: {r['content'][:300]}")
    return "\n".join(formatted) if formatted else "No results found."


def format_reference_list(sources: list) -> str:
    """Turns the collected sources into a numbered Markdown reference list."""
    if not sources:
        return ""
    lines = [f"[{s['id']}] {s['title']} - {s['url']}" for s in sources]
    return "\n## References\n" + "\n".join(lines)


def make_plan(topic: str) -> str:
    """
    STEP 1: Planning.
    Ask the model to break the topic into sub-questions BEFORE any searching happens.
    This is a separate, visible call so you can show task decomposition explicitly.
    """
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=(
            f"I want to write a well-researched report on: '{topic}'. "
            f"Before any research happens, break this topic down into 3-5 specific "
            f"sub-questions that, if answered, would let me write a thorough report. "
            f"Return ONLY a numbered list, nothing else."
        )
    )
    return response.text


def gather_and_draft(topic: str, plan: str, sources: list, max_turns: int = 6) -> str:
    """
    STEP 2: Research + draft.
    The core agent loop:
    1. Send the conversation to Gemini
    2. If Gemini wants to use a tool, run it and feed the result back
    3. Repeat until Gemini gives a final text answer (no more tool calls)

    `sources` is a shared list (created in research()) that gets filled in as
    run_search() is called, so every citation traces back to a real URL.
    """
    contents = [
        types.Content(
            role="user",
            parts=[types.Part(text=(
                f"I need a well-researched report on: '{topic}'. "
                f"Here is the research plan to follow:\n{plan}\n\n"
                f"Use the web_search tool as many times as needed to answer each "
                f"sub-question in the plan before writing the final report. "
                f"Each search result will come back with a source ID like [1], [2]. "
                f"When you write the report, cite claims using those exact IDs, e.g. "
                f"'AI adoption reached 80% [3].' Do not invent citations or use vague "
                f"phrases like 'industry reports show' without a bracketed ID. "
                f"Write a clear, well-structured draft report with a short intro, "
                f"key findings with inline [n] citations, and a conclusion."
            ))]
        )
    ]

    for turn in range(max_turns):
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=contents,
            config=config
        )

        candidate = response.candidates[0]
        function_calls = [
            part.function_call for part in candidate.content.parts
            if part.function_call is not None
        ]

        # Add the model's response to the conversation history
        contents.append(candidate.content)

        if not function_calls:
            # No tool call = model is done, this is the final report
            final_text = "".join(
                part.text for part in candidate.content.parts if part.text
            )
            return final_text

        # Run each requested tool call and send results back
        function_response_parts = []
        for fc in function_calls:
            if fc.name == "web_search":
                query = fc.args["query"]
                result_text = run_search(query, sources)
                function_response_parts.append(
                    types.Part.from_function_response(
                        name="web_search",
                        response={"result": result_text}
                    )
                )

        contents.append(types.Content(role="user", parts=function_response_parts))

    return "⚠️ Hit max turns without finishing. Consider raising max_turns."


def critique_and_revise(topic: str, draft: str, rounds: int = 2) -> str:
    """
    STEP 3: Self-critique and revise, run for multiple rounds.
    One pass often catches issues but doesn't fully fix all of them -
    so we critique the REVISED version again, up to `rounds` times.
    This is what makes it a real reflection loop instead of a single rewrite.
    """
    current_version = draft

    for i in range(rounds):
        print(f"\n🔍 Critique round {i + 1} of {rounds}...")

        critique_response = client.models.generate_content(
            model=MODEL_NAME,
            contents=(
                f"Here is a draft research report on '{topic}':\n\n{current_version}\n\n"
                f"Critically review this draft. List specific weaknesses: claims made "
                f"WITHOUT a bracketed [n] citation, gaps in coverage, or unclear "
                f"structure. Flag every sentence that states a fact or statistic "
                f"without a [n] tag right after it. Also flag any [n] reference in "
                f"the References list that is never actually cited in the body text. "
                f"Be honest and specific, not generic."
            )
        )
        critique = critique_response.text
        print(f"\n📝 Critique (round {i + 1}):\n" + critique)

        revision_response = client.models.generate_content(
            model=MODEL_NAME,
            contents=(
                f"Current draft report on '{topic}':\n\n{current_version}\n\n"
                f"Critique of that draft:\n\n{critique}\n\n"
                f"Now write a final, improved version of the report that FULLY "
                f"addresses every single point in this critique - not just some of "
                f"them. Keep all existing [n] citation tags exactly as they are "
                f"(do not renumber or remove them), and either add a [n] citation "
                f"to every claim the critique flagged as unsupported, or soften/remove "
                f"that claim if no source supports it. Return ONLY the final report."
            )
        )
        current_version = revision_response.text

    return current_version


def research(topic: str) -> str:
    """Full pipeline: plan -> gather & draft -> critique -> revise."""
    sources = []  # shared list, filled in by run_search() as it's called

    print("🧭 Planning research...")
    plan = make_plan(topic)
    print("\n📋 Research plan:\n" + plan)

    print("\n🔎 Gathering information and writing draft...")
    draft = gather_and_draft(topic, plan, sources)
    print("\n📄 Draft complete.")

    print("\n🔍 Reviewing and revising...")
    final_report = critique_and_revise(topic, draft)

    # Append the real reference list, built from actual searched URLs -
    # not written by the model, so it can't be hallucinated.
    final_report += "\n" + format_reference_list(sources)

    return final_report


if __name__ == "__main__":
    topic = input("What topic do you want researched? ")
    report = research(topic)
    print("\n" + "=" * 60)
    print("FINAL REPORT")
    print("=" * 60)
    print(report)

    # Save it to a file too
    with open("report.md", "w", encoding="utf-8") as f:
        f.write(report)
    print("\n✅ Report also saved to report.md")