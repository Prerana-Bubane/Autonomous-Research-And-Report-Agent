"""
Exports a diagram of your agent's graph structure.

Run this with: python diagram_export.py

This produces:
1. graph_diagram.mmd - Mermaid diagram source (paste into README.md inside a
   ```mermaid fence, GitHub renders these automatically)
2. graph_diagram.png - an actual image file (requires internet access to
   mermaid.ink's rendering service; skip if you're offline or it fails)
"""

from agent_langgraph import app

# Get the graph structure from your compiled LangGraph app
graph = app.get_graph()

# --- Option 1: Mermaid text (always works, no internet needed) ---
mermaid_text = graph.draw_mermaid()
with open("graph_diagram.mmd", "w", encoding="utf-8") as f:
    f.write(mermaid_text)
print("✅ Saved graph_diagram.mmd")
print("\nPaste this into your README.md wrapped in a ```mermaid code fence:\n")
print(mermaid_text)

# --- Option 2: PNG image (needs internet, calls mermaid.ink to render) ---
try:
    png_bytes = graph.draw_mermaid_png()
    with open("graph_diagram.png", "wb") as f:
        f.write(png_bytes)
    print("\n✅ Also saved graph_diagram.png")
except Exception as e:
    print(f"\n⚠️ Couldn't generate PNG (needs internet access): {e}")
    print("The .mmd text version above still works fine for your README.")