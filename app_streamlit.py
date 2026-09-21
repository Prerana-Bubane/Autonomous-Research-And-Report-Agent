"""
Streamlit UI for the Autonomous Research Agent.

Setup (in addition to what you already have):
    pip install streamlit

Run this with:
    streamlit run app_streamlit.py

This does NOT run the graph all at once and dump the final text - it uses
app.stream() so you can see the plan, draft, each critique round, and the
final report appear one at a time as the agent actually works through them.
"""

import streamlit as st
import os

# Bridge Streamlit Cloud's "Secrets" (set in the app dashboard when deployed)
# into environment variables, BEFORE importing agent_langgraph - since that
# module reads os.getenv() the moment it's imported. Locally, st.secrets will
# just be empty and this block does nothing, so your .env file still works
# exactly as before.
try:
    if "GEMINI_API_KEY" in st.secrets:
        os.environ["GEMINI_API_KEY"] = st.secrets["GEMINI_API_KEY"]
    if "TAVILY_API_KEY" in st.secrets:
        os.environ["TAVILY_API_KEY"] = st.secrets["TAVILY_API_KEY"]
except Exception:
    pass  # no secrets.toml locally - that's fine, .env handles it instead

from agent_langgraph import app

st.set_page_config(page_title="Autonomous Research Agent", page_icon="🔎", layout="centered")

st.title("🔎 Autonomous Research Agent")
st.caption("Plans a research strategy, searches the web, drafts a report, and critiques its own work before finalizing.")

topic = st.text_input("What topic do you want researched?", placeholder="e.g. Impact of AI on software development")
max_rounds = st.slider("Critique rounds", min_value=1, max_value=3, value=2)
start = st.button("Start Research", type="primary", disabled=not topic)

if start:
    initial_state = {
        "topic": topic,
        "plan": "",
        "sources": [],
        "draft": "",
        "current_version": "",
        "critique": "",
        "round": 0,
        "max_rounds": max_rounds,
        "final_report": ""
    }

    plan_box = st.empty()
    draft_box = st.empty()
    critique_boxes = []
    final_box = st.empty()

    with st.status("Agent is working...", expanded=True) as status:
        for step_output in app.stream(initial_state):
            # step_output looks like {"node_name": {state updates from that node}}
            node_name = list(step_output.keys())[0]
            node_data = step_output[node_name]

            if node_name == "plan":
                status.update(label="📋 Planning research...")
                with plan_box.expander("📋 Research Plan", expanded=True):
                    st.markdown(node_data["plan"])

            elif node_name == "draft":
                status.update(label="🔎 Gathering info and writing draft...")
                with draft_box.expander("📄 First Draft", expanded=False):
                    st.markdown(node_data["draft"])

            elif node_name == "critique":
                status.update(label=f"🔍 Critique round in progress...")
                box = st.empty()
                with box.expander(f"📝 Critique", expanded=False):
                    st.markdown(node_data["critique"])
                critique_boxes.append(box)

            elif node_name == "revise":
                status.update(label=f"✏️ Revising (round {node_data['round']})...")

            elif node_name == "finalize":
                status.update(label="✅ Done!", state="complete")
                with final_box.container():
                    st.subheader("Final Report")
                    st.markdown(node_data["final_report"])
                    st.download_button(
                        "Download report as Markdown",
                        data=node_data["final_report"],
                        file_name="report.md",
                        mime="text/markdown"
                    )