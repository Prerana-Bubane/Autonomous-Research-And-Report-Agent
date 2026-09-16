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


def run_search(query: str) -> str:
    """Actually calls Tavily and returns a short text summary of results."""
    print(f"\n🔍 Agent is searching for: '{query}'")
    results = tavily.search(query=query, max_results=4)
    formatted = []
    for r in results.get("results", []):
        formatted.append(f"- {r['title']}: {r['content'][:300]} (source: {r['url']})")
    return "\n".join(formatted) if formatted else "No results found."


def research(topic: str, max_turns: int = 6):
    """
    The core agent loop:
    1. Send the conversation to Gemini
    2. If Gemini wants to use a tool, run it and feed the result back
    3. Repeat until Gemini gives a final text answer (no more tool calls)
    """
    contents = [
        types.Content(
            role="user",
            parts=[types.Part(text=(
                f"I need a well-researched report on: '{topic}'. "
                f"Use the web_search tool as many times as needed to gather enough "
                f"information from multiple angles before writing the final report. "
                f"When you have enough information, write a clear, well-structured "
                f"report with a short intro, key findings with sources, and a conclusion."
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
                result_text = run_search(query)
                function_response_parts.append(
                    types.Part.from_function_response(
                        name="web_search",
                        response={"result": result_text}
                    )
                )

        contents.append(types.Content(role="user", parts=function_response_parts))

    return "⚠️ Hit max turns without finishing. Consider raising max_turns."


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