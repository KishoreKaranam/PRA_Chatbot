"""
Generate Solution Architecture Diagram for PRA Chatbot.
Pure matplotlib approach - no external image downloads needed.
Produces a professional, color-coded architecture diagram.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle

OUTPUT_FILE = Path(__file__).parent / "PRA_Chatbot_Architecture.png"

# ── Color palette ────────────────────────────────────────────────────────────
COLORS = {
    "bg": "#F8FAFC",
    "title": "#0F172A",
    "subtitle": "#64748B",
    "user_box": "#DBEAFE",
    "user_border": "#2563EB",
    "fe_box": "#DCFCE7",
    "fe_border": "#16A34A",
    "be_box": "#FEF3C7",
    "be_border": "#D97706",
    "kg_box": "#F3E8FF",
    "kg_border": "#7C3AED",
    "llm_box": "#FCE7F3",
    "llm_border": "#DB2777",
    "embed_box": "#DBEAFE",
    "embed_border": "#1D4ED8",
    "arrow": "#475569",
}


def draw_component(ax, x, y, w, h, label, sublabel, icon_text, icon_color,
                   bg_color="#FFFFFF", border_color="#CBD5E1", fontsize=9):
    """Draw a single component box with an icon circle and labels."""
    box = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.008",
        facecolor=bg_color,
        edgecolor=border_color,
        linewidth=1.5,
        zorder=3,
    )
    ax.add_patch(box)
    circle = Circle(
        (x + w / 2, y + h * 0.65), radius=min(w, h) * 0.18,
        facecolor=icon_color, edgecolor="white", linewidth=1.5, zorder=4
    )
    ax.add_patch(circle)
    ax.text(x + w / 2, y + h * 0.65, icon_text, ha="center", va="center",
            fontsize=11, fontweight="bold", color="white", zorder=5)
    ax.text(x + w / 2, y + h * 0.28, label, ha="center", va="center",
            fontsize=fontsize, fontweight="bold", color="#1E293B", zorder=5)
    if sublabel:
        ax.text(x + w / 2, y + h * 0.10, sublabel, ha="center", va="center",
                fontsize=7, color="#64748B", zorder=5)


def draw_group_box(ax, x, y, w, h, label, bg_color, border_color):
    """Draw a grouped section box."""
    box = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.012",
        facecolor=bg_color,
        edgecolor=border_color,
        linewidth=2,
        alpha=0.6,
        zorder=1,
    )
    ax.add_patch(box)
    ax.text(x + w / 2, y + h + 0.012, label, ha="center", va="bottom",
            fontsize=10, fontweight="bold", color=border_color,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                      edgecolor=border_color, linewidth=1),
            zorder=6)


def draw_arrow(ax, start, end, color="#475569", lw=1.8, label="", curve=0.0):
    """Draw a connecting arrow with optional label."""
    arrow = FancyArrowPatch(
        start, end,
        connectionstyle=f"arc3,rad={curve}",
        arrowstyle="->",
        color=color,
        linewidth=lw,
        mutation_scale=18,
        zorder=2,
    )
    ax.add_patch(arrow)
    if label:
        mx = (start[0] + end[0]) / 2
        my = (start[1] + end[1]) / 2
        ax.text(mx, my + 0.018, label, ha="center", va="bottom",
                fontsize=7, color=color, style="italic", zorder=6,
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                          edgecolor="none", alpha=0.8))


def main():
    fig, ax = plt.subplots(1, 1, figsize=(20, 12))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])

    # ═══════════════════════════════════════════════════════════════════════════
    # TITLE
    # ═══════════════════════════════════════════════════════════════════════════
    ax.text(0.50, 0.97, "PRA Chatbot - Solution Architecture",
            ha="center", va="top", fontsize=22, fontweight="bold", color=COLORS["title"])
    ax.text(0.50, 0.935, "Payment Reference Architecture | Knowledge Graph | AI-Powered Q&A",
            ha="center", va="top", fontsize=12, color=COLORS["subtitle"])

    # ═══════════════════════════════════════════════════════════════════════════
    # LAYER 1: USERS / CHANNELS
    # ═══════════════════════════════════════════════════════════════════════════
    draw_group_box(ax, 0.03, 0.77, 0.22, 0.13, "Channels & Users",
                   COLORS["user_box"], COLORS["user_border"])

    draw_component(ax, 0.05, 0.785, 0.08, 0.095, "Browser", "Web App",
                   "U", "#2563EB", bg_color="#EFF6FF", border_color="#93C5FD")
    draw_component(ax, 0.15, 0.785, 0.08, 0.095, "API", "REST Client",
                   "{}",  "#0891B2", bg_color="#ECFEFF", border_color="#67E8F9")

    # ═══════════════════════════════════════════════════════════════════════════
    # LAYER 2: FRONTEND (React + Vite + TypeScript)
    # ═══════════════════════════════════════════════════════════════════════════
    draw_group_box(ax, 0.30, 0.77, 0.40, 0.13, "Presentation Layer (SPA)",
                   COLORS["fe_box"], COLORS["fe_border"])

    draw_component(ax, 0.32, 0.785, 0.10, 0.095, "React 18", "Components",
                   "R", "#61DAFB", bg_color="#F0FDF4", border_color="#86EFAC")
    draw_component(ax, 0.44, 0.785, 0.10, 0.095, "Vite 8", "Build Tool",
                   "V", "#646CFF", bg_color="#F0FDF4", border_color="#86EFAC")
    draw_component(ax, 0.56, 0.785, 0.12, 0.095, "TypeScript", "Type Safety",
                   "TS", "#3178C6", bg_color="#F0FDF4", border_color="#86EFAC")

    ax.text(0.50, 0.775, "localhost:5173", ha="center", fontsize=7,
            color="#16A34A", style="italic")

    # ═══════════════════════════════════════════════════════════════════════════
    # LAYER 3: BACKEND (FastAPI + Services)
    # ═══════════════════════════════════════════════════════════════════════════
    draw_group_box(ax, 0.08, 0.48, 0.84, 0.23, "API & Orchestration Layer",
                   COLORS["be_box"], COLORS["be_border"])

    draw_component(ax, 0.10, 0.52, 0.12, 0.11, "FastAPI", "Port 8001",
                   "F", "#009688", bg_color="#FFFBEB", border_color="#FCD34D")

    draw_component(ax, 0.24, 0.52, 0.12, 0.11, "Python 3.11", "Async Runtime",
                   "Py", "#3776AB", bg_color="#FFFBEB", border_color="#FCD34D")

    # Services
    services = [
        ("SPARQL\nService", "SQ", "#7C3AED", 0.40),
        ("FTS\nService", "FT", "#EA580C", 0.53),
        ("Similarity\nService", "SS", "#2563EB", 0.66),
        ("Answer\nService", "AS", "#DB2777", 0.79),
    ]
    for label, icon, color, xpos in services:
        draw_component(ax, xpos, 0.52, 0.11, 0.11, label, "",
                       icon, color, bg_color="#FFFBEB", border_color="#FCD34D", fontsize=8)

    ax.text(0.50, 0.50, "Retrieval-Augmented Generation (RAG) Pipeline",
            ha="center", fontsize=8, color="#92400E", style="italic")

    # ═══════════════════════════════════════════════════════════════════════════
    # LAYER 4: KNOWLEDGE GRAPH
    # ═══════════════════════════════════════════════════════════════════════════
    draw_group_box(ax, 0.03, 0.08, 0.30, 0.32, "Knowledge Graph Layer",
                   COLORS["kg_box"], COLORS["kg_border"])

    draw_component(ax, 0.05, 0.24, 0.12, 0.11, "GraphDB 10", "Ontotext",
                   "G", "#FF6600", bg_color="#FAF5FF", border_color="#D8B4FE")
    draw_component(ax, 0.19, 0.24, 0.12, 0.11, "rdflib 7", "In-Memory",
                   "rdf", "#4CAF50", bg_color="#FAF5FF", border_color="#D8B4FE")

    # TTL file
    box = FancyBboxPatch(
        (0.06, 0.10), 0.24, 0.10,
        boxstyle="round,pad=0.008",
        facecolor="#EDE9FE",
        edgecolor="#7C3AED",
        linewidth=1.5, zorder=3,
    )
    ax.add_patch(box)
    ax.text(0.18, 0.165, "pra_ontology.ttl", ha="center", fontsize=9,
            fontweight="bold", color="#5B21B6", zorder=5)
    ax.text(0.18, 0.125, "6,291 RDF Triples | SPARQL 1.1 | OWL2",
            ha="center", fontsize=7, color="#7C3AED", zorder=5)

    # ═══════════════════════════════════════════════════════════════════════════
    # LAYER 4: LLM (Anthropic Claude)
    # ═══════════════════════════════════════════════════════════════════════════
    draw_group_box(ax, 0.36, 0.08, 0.27, 0.32, "LLM Layer (Chat & Reasoning)",
                   COLORS["llm_box"], COLORS["llm_border"])

    draw_component(ax, 0.40, 0.24, 0.19, 0.11, "Anthropic Claude", "Sonnet 4",
                   "A", "#191919", bg_color="#FDF2F8", border_color="#F9A8D4")

    features_llm = [
        "Grounded answer generation",
        "Citation & evidence linking",
        "Multi-style output (Business/Technical)",
        "Context-aware reasoning",
    ]
    for i, feat in enumerate(features_llm):
        ax.text(0.395, 0.205 - i * 0.028, f"* {feat}",
                fontsize=7, color="#831843", zorder=5)

    # ═══════════════════════════════════════════════════════════════════════════
    # LAYER 4: EMBEDDINGS (Azure OpenAI)
    # ═══════════════════════════════════════════════════════════════════════════
    draw_group_box(ax, 0.66, 0.08, 0.30, 0.32, "Embedding Layer (Vector Search)",
                   COLORS["embed_box"], COLORS["embed_border"])

    draw_component(ax, 0.68, 0.24, 0.12, 0.11, "Azure OpenAI", "Embeddings",
                   "Az", "#0078D4", bg_color="#EFF6FF", border_color="#93C5FD")
    draw_component(ax, 0.82, 0.24, 0.12, 0.11, "NumPy", "Vector Store",
                   "Np", "#013243", bg_color="#EFF6FF", border_color="#93C5FD")

    features_embed = [
        "text-embedding-3-large",
        "Cosine similarity search",
        "In-memory vector index",
        "Batch entity encoding",
    ]
    for i, feat in enumerate(features_embed):
        ax.text(0.68, 0.205 - i * 0.028, f"* {feat}",
                fontsize=7, color="#1E40AF", zorder=5)

    # ═══════════════════════════════════════════════════════════════════════════
    # ARROWS (Data Flow)
    # ═══════════════════════════════════════════════════════════════════════════

    # Users -> Frontend
    draw_arrow(ax, (0.25, 0.835), (0.30, 0.835),
               color=COLORS["user_border"], lw=2.5, label="HTTPS")

    # Frontend -> Backend
    draw_arrow(ax, (0.50, 0.77), (0.50, 0.71),
               color=COLORS["fe_border"], lw=2.5, label="/api/* (REST)")

    # Backend -> Knowledge Graph
    draw_arrow(ax, (0.26, 0.52), (0.18, 0.40),
               color=COLORS["kg_border"], lw=2, label="SPARQL + FTS", curve=0.1)

    # Backend -> LLM
    draw_arrow(ax, (0.50, 0.52), (0.50, 0.40),
               color=COLORS["llm_border"], lw=2, label="Chat Completion")

    # Backend -> Embeddings
    draw_arrow(ax, (0.74, 0.52), (0.80, 0.40),
               color=COLORS["embed_border"], lw=2, label="Embedding API", curve=-0.1)

    # ═══════════════════════════════════════════════════════════════════════════
    # LEGEND (bottom)
    # ═══════════════════════════════════════════════════════════════════════════
    legend_y = 0.025
    ax.axhline(y=0.055, xmin=0.03, xmax=0.97, color="#E2E8F0", linewidth=1, zorder=1)

    legend_items = [
        ("React + Vite + TS", "#16A34A"),
        ("FastAPI + Python 3.11", "#D97706"),
        ("Anthropic Claude Sonnet 4", "#DB2777"),
        ("Azure OpenAI Embeddings", "#1D4ED8"),
        ("GraphDB / rdflib (SPARQL)", "#7C3AED"),
    ]
    ax.text(0.03, legend_y, "Technology Stack:", fontsize=9, fontweight="bold",
            color="#334155", va="center")
    x_pos = 0.17
    for text, color in legend_items:
        ax.plot(x_pos, legend_y, "s", color=color, markersize=10)
        ax.text(x_pos + 0.015, legend_y, text, fontsize=8, color=color,
                va="center", fontweight="bold")
        x_pos += 0.17

    # ═══════════════════════════════════════════════════════════════════════════
    # FLOW DESCRIPTION (right side)
    # ═══════════════════════════════════════════════════════════════════════════
    flow_x = 0.76
    flow_y = 0.90
    ax.text(flow_x, flow_y, "Data Flow", fontsize=10, fontweight="bold", color="#334155")
    flows = [
        "1. User sends question via React UI",
        "2. Frontend calls FastAPI /api/ask",
        "3. Backend orchestrates RAG pipeline:",
        "   a. SPARQL queries Knowledge Graph",
        "   b. FTS does full-text search",
        "   c. Similarity embeds & searches",
        "4. Evidence passed to Anthropic Claude",
        "5. Grounded answer returned to UI",
    ]
    for i, f in enumerate(flows):
        ax.text(flow_x, flow_y - 0.028 * (i + 1), f,
                fontsize=7, color="#475569", family="monospace")

    # ── Save ──────────────────────────────────────────────────────────────────
    plt.tight_layout(pad=0.5)
    plt.savefig(OUTPUT_FILE, dpi=200, bbox_inches="tight", facecolor=COLORS["bg"])
    plt.close()
    print(f"\nArchitecture diagram saved to:\n   {OUTPUT_FILE}")
    print(f"   Resolution: ~4000x2400 px (200 DPI)")
    print(f"   Size: {OUTPUT_FILE.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
