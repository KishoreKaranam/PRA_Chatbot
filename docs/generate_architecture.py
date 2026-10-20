"""Build the PRA Chatbot & Agent Layer architecture diagram (v5.1) as SVG.

Recreated from the v5.0 image, with corrections to match the running system.
Edit the TEXT constants / blocks below and re-run to regenerate.
usage: python generate_architecture.py [out.svg]
(default: PRA_Chatbot_Architecture.svg next to this script; standard library only)
"""
import sys
from xml.sax.saxutils import escape as esc

W, H = 2000, 1800
out: list[str] = []
add = out.append

# ── palette ──────────────────────────────────────────────────────────────────
INK, BODY, MUTED, FAINT = "#0f172a", "#334155", "#64748b", "#94a3b8"
LINE, CARD, SOFT = "#e2e8f0", "#ffffff", "#f8fafc"
INDIGO, INDIGO_BG, INDIGO_LINE = "#4f46e5", "#f5f7ff", "#c7d2fe"
SKY, SKY_BG, SKY_LINE = "#0ea5e9", "#f0f9ff", "#bae6fd"
GREEN, GREEN_BG, GREEN_LINE, GREEN_SUB = "#047857", "#ecfdf5", "#86efac", "#4b7d6a"
AMBER, AMBER_DK, AMBER_BG, AMBER_LINE, AMBER_SUB = "#d6a531", "#92400e", "#fffaeb", "#f2d58a", "#7c6a3c"
ARROW = "#94a3b8"

TECH = {  # chip icon colour + glyph
    "React 19": ("#61dafb", "⚛"), "Vite": ("#a855f7", "⚡"), "TypeScript": ("#3178c6", "TS"),
    "HTTPS · SSE streaming": ("#64748b", "🔒"), "Microsoft Entra ID": ("#0078d4", "▲"),
    "OAuth 2.0 · OIDC": ("#64748b", "🔒"), "FastAPI": ("#059669", "⚡"), "LangGraph": ("#1c3c3c", "∞"),
    "Python": ("#3776ab", "Py"), "Claude": ("#d97757", "✳"), "Claude Sonnet": ("#d97757", "✳"),
    "Azure AI Foundry": ("#0078d4", "▲"), "Azure OpenAI": ("#0078d4", "▲"), "Neo4j": ("#018bff", "◆"),
    "PostgreSQL": ("#336791", "🐘"), "SQLAlchemy async": ("#b91c1c", ""), "Cypher + Lucene full-text": ("#16a34a", "☆"),
}


def t(x, y, s, size=12, fill=BODY, weight=400, anchor="start", italic=False, ls=None):
    extra = ' font-style="italic"' if italic else ""
    extra += f' letter-spacing="{ls}"' if ls else ""
    add(f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" font-weight="{weight}" '
        f'text-anchor="{anchor}"{extra}>{esc(s)}</text>')


def rect(x, y, w, h, fill=CARD, stroke=LINE, rx=10, sw=1, dash=None, extra=""):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" '
        f'stroke-width="{sw}"{d}{extra}/>')


def text_w(s, size):  # rough width estimate for layout of pills
    return len(s) * size * 0.58


def chip(x, y, label, anchor="start", on_dark=False):
    """Technology pill. Returns its width. anchor='end' → x is the right edge."""
    color, glyph = TECH.get(label, (MUTED, ""))
    w = text_w(label, 10.5) + (34 if glyph or True else 18)
    if anchor == "end":
        x -= w
    rect(x, y, w, 23, fill="#ffffff", stroke="#ffffff" if on_dark else LINE, rx=11.5)
    add(f'<circle cx="{x + 13}" cy="{y + 11.5}" r="7" fill="{color}"/>')
    if glyph:
        add(f'<text x="{x + 13}" y="{y + 15}" font-size="8" fill="#ffffff" font-weight="700" '
            f'text-anchor="middle">{esc(glyph if len(glyph) <= 2 else glyph[0])}</text>')
    t(x + 26, y + 15.5, label, 10.5, INK, 700)
    return w


def chips_right(right, y, labels):
    for label in reversed(labels):
        right -= chip(right, y, label, anchor="end") + 8


def chips_left(x, y, labels, on_dark=False):
    for label in labels:
        x += chip(x, y, label, on_dark=on_dark) + 8


def badge(x_right, y, kind):
    styles = {
        "LIVE NOW": (GREEN_BG, "#10b981", GREEN, True),
        "PARTLY LIVE": ("#eff6ff", "#60a5fa", "#1d4ed8", True),
        "PLANNED": (SOFT, "#cbd5e1", "#475569", False),
        "OFFLINE · SEPARATE SERVICE": ("#fef3c7", AMBER, AMBER_DK, False),
    }
    bg, line, fg, dot = styles[kind]
    w = len(kind) * 9.5 * 0.7 + len(kind) * 0.6 + (30 if dot else 20)
    x = x_right - w
    rect(x, y, w, 20, fill=bg, stroke=line, rx=10)
    if dot:
        add(f'<circle cx="{x + 11}" cy="{y + 10}" r="3" fill="{line}"/>')
    t(x + (19 if dot else 10), y + 14, kind, 9.5, fg, 700, ls=0.6)
    return x


def arrow_v(x, y1, y2, two_way=True, color=ARROW, width=2, dash=None, head="arrow"):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    start = f' marker-start="url(#{head}Start)"' if two_way else ""
    add(f'<line x1="{x}" y1="{y1}" x2="{x}" y2="{y2}" stroke="{color}" stroke-width="{width}"{d}'
        f'{start} marker-end="url(#{head})"/>')


def rail(y, *lines):
    for i, s in enumerate(lines):
        t(34, y + i * 15, s, 9.5, MUTED, 700, ls=0.6)


# ── icons (simple line glyphs) ───────────────────────────────────────────────
def icon(kind, cx, cy, color=INDIGO, s=1.0):
    g = f'<g transform="translate({cx},{cy}) scale({s})" fill="none" stroke="{color}" stroke-width="1.8" ' \
        f'stroke-linecap="round" stroke-linejoin="round">'
    body = {
        "react": '<circle r="3" fill="{c}" stroke="none"/><ellipse rx="16" ry="6"/>'
                 '<ellipse rx="16" ry="6" transform="rotate(60)"/><ellipse rx="16" ry="6" transform="rotate(120)"/>',
        "shield": '<path d="M0,-13 L11,-8 L11,1 Q11,10 0,14 Q-11,10 -11,1 L-11,-8 Z"/><circle cy="-1" r="3"/>'
                  '<line x1="0" y1="2" x2="0" y2="7"/>',
        "hub": '<circle r="4"/><circle cx="0" cy="-13" r="3"/><circle cx="11" cy="-6" r="3"/><circle cx="11" cy="7" r="3"/>'
               '<circle cx="0" cy="13" r="3"/><circle cx="-11" cy="7" r="3"/><circle cx="-11" cy="-6" r="3"/>'
               '<line x1="0" y1="-4" x2="0" y2="-10"/><line x1="3.5" y1="-2" x2="8.5" y2="-5"/>'
               '<line x1="3.5" y1="2" x2="8.5" y2="5"/><line x1="0" y1="4" x2="0" y2="10"/>'
               '<line x1="-3.5" y1="2" x2="-8.5" y2="5"/><line x1="-3.5" y1="-2" x2="-8.5" y2="-5"/>',
        "people": '<circle cx="-5" cy="-6" r="5"/><path d="M-14,10 Q-14,0 -5,0 Q4,0 4,10"/>'
                  '<rect x="4" y="-12" width="12" height="9" rx="2"/><line x1="7" y1="-8" x2="13" y2="-8"/>',
        "person_chat": '<circle cx="-5" cy="-5" r="5"/><path d="M-14,12 Q-14,1 -5,1 Q4,1 4,12"/>'
                       '<rect x="5" y="-13" width="12" height="9" rx="2"/>',
        "bulb": '<path d="M-6,4 Q-11,-2 -9,-8 Q-6,-14 0,-14 Q6,-14 9,-8 Q11,-2 6,4 L6,8 L-6,8 Z"/>'
                '<line x1="-4" y1="12" x2="4" y2="12"/><line x1="12" y1="-13" x2="12" y2="10"/>',
        "chart_person": '<circle cx="-8" cy="-5" r="4"/><path d="M-15,10 Q-15,1 -8,1 Q-1,1 -1,10"/>'
                        '<rect x="2" y="-12" width="15" height="13" rx="1"/><line x1="6" y1="-2" x2="6" y2="-6"/>'
                        '<line x1="10" y1="-2" x2="10" y2="-9"/><line x1="14" y1="-2" x2="14" y2="-5"/>',
        "blocks": '<rect x="-13" y="-13" width="26" height="7"/><rect x="-13" y="-3" width="11" height="7"/>'
                  '<rect x="2" y="-3" width="11" height="7"/><rect x="-13" y="7" width="26" height="7"/>',
        "clipboard": '<rect x="-10" y="-11" width="20" height="25" rx="2"/><rect x="-5" y="-14" width="10" height="5" rx="1"/>'
                     '<line x1="-5" y1="-3" x2="5" y2="-3"/><line x1="-5" y1="3" x2="5" y2="3"/><line x1="-5" y1="9" x2="3" y2="9"/>',
        "doc_pen": '<path d="M-10,-13 L4,-13 L10,-7 L10,13 L-10,13 Z"/><line x1="-6" y1="-5" x2="5" y2="-5"/>'
                   '<line x1="-6" y1="1" x2="5" y2="1"/><path d="M4,14 L12,6 L15,9 L7,17 Z"/>',
        "sliders": '<line x1="-13" y1="-8" x2="13" y2="-8"/><line x1="-13" y1="0" x2="13" y2="0"/>'
                   '<line x1="-13" y1="8" x2="13" y2="8"/><circle cx="-4" cy="-8" r="3" fill="#fff"/>'
                   '<circle cx="6" cy="0" r="3" fill="#fff"/><circle cx="-7" cy="8" r="3" fill="#fff"/>',
        "check_doc": '<path d="M-10,-13 L4,-13 L10,-7 L10,6"/><path d="M-10,-13 L-10,13 L0,13"/>'
                     '<line x1="-6" y1="-5" x2="5" y2="-5"/><line x1="-6" y1="1" x2="2" y2="1"/>'
                     '<path d="M3,10 L7,14 L14,6"/>',
        "db": '<ellipse cy="-9" rx="11" ry="4"/><path d="M-11,-9 L-11,9 Q0,15 11,9 L11,-9"/>'
              '<path d="M-11,0 Q0,6 11,0"/>',
        "chat": '<path d="M-12,-10 L12,-10 L12,6 L-2,6 L-8,12 L-8,6 L-12,6 Z"/>'
                '<circle cx="-5" cy="-2" r="1" fill="{c}"/><circle cx="0" cy="-2" r="1" fill="{c}"/><circle cx="5" cy="-2" r="1" fill="{c}"/>',
        "docs": '<rect x="-8" y="-13" width="18" height="23" rx="1"/><path d="M-12,-9 L-12,14 L6,14"/>'
                '<line x1="-4" y1="-6" x2="6" y2="-6"/><line x1="-4" y1="-1" x2="6" y2="-1"/><line x1="-4" y1="4" x2="4" y2="4"/>',
    }[kind].replace("{c}", color)
    add(g + body + "</g>")


# ══════════════════════════════════════════════════════════════════════════════
add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
    'font-family="Segoe UI, Helvetica, Arial, sans-serif">')
add('''<defs>
  <linearGradient id="hdr" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#2563eb"/><stop offset="1" stop-color="#7c3aed"/></linearGradient>
  <linearGradient id="kg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1d7ae0"/><stop offset="1" stop-color="#0b4fb0"/></linearGradient>
  <marker id="arrow" markerUnits="userSpaceOnUse" markerWidth="11" markerHeight="11" refX="9" refY="5.5" orient="auto"><path d="M0,0 L11,5.5 L0,11 Z" fill="#94a3b8"/></marker><marker id="_unused1" markerWidth="1" markerHeight="1"><path d="M0,0 L10,5 L0,10 Z" fill="#94a3b8"/></marker>
  <marker id="arrowStart" markerUnits="userSpaceOnUse" markerWidth="11" markerHeight="11" refX="2" refY="5.5" orient="auto"><path d="M11,0 L0,5.5 L11,11 Z" fill="#94a3b8"/></marker><marker id="_unused2" markerWidth="1" markerHeight="1"><path d="M10,0 L0,5 L10,10 Z" fill="#94a3b8"/></marker>
  <marker id="amber" markerUnits="userSpaceOnUse" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto"><path d="M0,0 L12,6 L0,12 Z" fill="#c8961e"/></marker><marker id="_unused3" markerWidth="1" markerHeight="1"><path d="M0,0 L10,5 L0,10 Z" fill="#c8961e"/></marker>
  <marker id="amberStart" markerWidth="10" markerHeight="10" refX="2" refY="5" orient="auto"><path d="M10,0 L0,5 L10,10 Z" fill="#c8961e"/></marker>
</defs>''')
add(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')

# ── header ───────────────────────────────────────────────────────────────────
add(f'<rect width="{W}" height="86" fill="url(#hdr)"/>')
add('<circle cx="61" cy="44" r="26" fill="none" stroke="#ffffff" stroke-opacity="0.85" stroke-width="2"/>')
icon("hub", 61, 44, "#ffffff", 1.05)
t(108, 40, "Payment Reference Architecture (PRA) — Chatbot & Agent Layer", 27, "#ffffff", 700)
t(110, 66, "Executive Architecture Overview  —  AI agents grounded in the PRA knowledge graph", 14, "#dbeafe")
t(1968, 48, "Confidential — Internal Use", 12.5, "#ffffff", 700, "end")

L, R = 131, 1339          # left column edges
LW = R - L

# ── 1. client ────────────────────────────────────────────────────────────────
rail(168, "CLIENT")
rect(L, 116, LW, 107)
icon("react", 175, 163, "#38bdf8", 1.05)
t(206, 157, "Web Chat Application", 21, INK, 700)
t(206, 178, "Browser-based chat — ask in plain English, get streamed answers with cited evidence and source links", 12.5, BODY)
t(206, 198, "Business Analysts & Payment Subject Matter Experts  ·  no installation required", 10.5, FAINT)
chips_right(1313, 137, ["React 19", "Vite", "TypeScript"])
chips_right(1313, 174, ["HTTPS · SSE streaming"])
arrow_v(735, 228, 258)

# ── 2. authentication ────────────────────────────────────────────────────────
rail(325, "IDENTITY", "& ACCESS")
rect(L, 262, LW, 122, fill=SKY_BG, stroke=SKY_LINE)
add(f'<rect x="{L}" y="262" width="6" height="122" fill="{SKY}"/>')
icon("shield", 173, 288, "#0e7490")
t(198, 286, "Authentication & Access", 19, INK, 700)
t(198, 306, "Every request arrives with a verified corporate identity and an entitlement scope — nothing reaches the agents anonymously", 12, BODY)
badge(1313, 272, "PLANNED")
chips_right(1313, 302, ["Microsoft Entra ID", "OAuth 2.0 · OIDC"])
for i, s in enumerate(["Single sign-on", "Token validated at the edge", "Role & data scope resolved",
                       "Identity carried to every agent & query"]):
    x = 156 + i * 293
    rect(x, 336, 279, 33, rx=7)
    t(x + 139.5, 357, s, 11.5, INK, 700, "middle")
arrow_v(735, 390, 420)

# ── 3. orchestration ─────────────────────────────────────────────────────────
rail(527, "ORCHESTRATION")
rect(L, 424, LW, 198)
icon("hub", 172, 462, INDIGO)
t(198, 458, "Orchestration Layer", 21, INK, 700)
badge(500, 444, "LIVE NOW")
t(198, 479, "The Orchestrator Agent — receives every request, routes it to the right specialist, and runs one auditable pipeline", 12.5, BODY)
chips_right(1313, 444, ["FastAPI", "LangGraph", "Python"])
steps = [("Understand the Request", "Intent, entities & conversation context"),
         ("Route to the Right Agent", "Picks the specialist for the job"),
         ("Retrieve Evidence", "Hybrid search over the knowledge graph"),
         ("Validate & Remember", "Confidence gate, then persist the turn")]
for i, (a, b) in enumerate(steps):
    x = 156 + i * 294
    rect(x, 510, 275, 75, fill=GREEN_BG, stroke=GREEN_LINE, rx=8)
    t(x + 137.5, 536, a, 14.5, GREEN, 700, "middle")
    t(x + 137.5, 556, b, 10.5, GREEN_SUB, 400, "middle")
    if i < 3:
        add(f'<line x1="{x + 277}" y1="547" x2="{x + 291}" y2="547" stroke="{GREEN_LINE}" stroke-width="2" marker-end="url(#arrow)"/>')
t(156, 606, "One reasoning pipeline for every agent — consistent, explainable, auditable", 12, MUTED, italic=True)
arrow_v(735, 628, 656)

# ── 4. agent layer ───────────────────────────────────────────────────────────
rail(860, "PRA AGENT", "LAYER")
rect(L, 662, LW, 422, fill=INDIGO_BG, stroke=INDIGO_LINE)
icon("people", 172, 690, INDIGO)
t(197, 686, "PRA Agent Layer", 21, INK, 700)
t(197, 708, "Specialist agents — each with one defined job; all share the same knowledge base, guardrails and audit trail", 12.5, BODY)
agents = [
    ("person_chat", "Payment Coach", "LIVE NOW", ["Domain Q&A on the PRA, answered with cited", "evidence and source document links"]),
    ("bulb", "Design Agent", "PLANNED", ["Exploratory sparring on solution design options"]),
    ("chart_person", "Impact Analysis Agent", "PLANNED", ["Assesses how a proposed change affects the", "existing solution"]),
    ("blocks", "Business Architecture Agent", "PLANNED", ["Frames the business architecture view for", "business development"]),
    ("clipboard", "Requirement Agent", "PLANNED", ["Captures and structures requirements against", "the PRA"]),
    ("doc_pen", "Story Builder Agent", "PLANNED", ["Builds user stories and acceptance criteria in", "the PRA structure"]),
    ("sliders", "Refinement Agent", "PLANNED", ["Challenges and refines drafts against the PRA"]),
]
for i, (ic, name, status, desc) in enumerate(agents):
    x = 156 + (i % 4) * 293
    y = 731 + (i // 4) * 172
    rect(x, y, 277, 153, stroke="#dbe3f0", rx=8)
    icon(ic, x + 30, y + 30, INDIGO)
    badge(x + 263, y + 14, status)
    t(x + 15, y + 67, name, 13.5, INK, 700)
    for j, line in enumerate(desc):
        t(x + 15, y + 87 + j * 15, line, 10.5, "#475569")
    chips_left(x + 15, y + 120, ["Claude"])
x, y = 156 + 3 * 293, 903
rect(x, y, 277, 153, fill="none", stroke="#a5b4fc", rx=8, dash="8,6", sw=1.5)
t(x + 138, y + 59, "Extensible by design", 13.5, FAINT, 700, "middle")
for j, line in enumerate(["New specialists plug into the same", "orchestrator, quality gate and shared services", "— no new plumbing"]):
    t(x + 138, y + 84 + j * 15, line, 10.5, FAINT, 400, "middle")
arrow_v(735, 1090, 1118)

# ── 5. quality gate ──────────────────────────────────────────────────────────
rail(1164, "QUALITY GATE")
rect(L, 1124, LW, 75, fill=INDIGO_BG, stroke=INDIGO_LINE)
add(f'<rect x="{L}" y="1124" width="6" height="75" fill="{INDIGO}"/>')
icon("check_doc", 172, 1152, INDIGO)
t(198, 1147, "Validator & Reviewer  —  the gate every agent output passes through", 16.5, INK, 700)
t(198, 1168, "Checks every claim against the retrieved evidence and links each fact to its source document; PRA compliance checks to follow", 12, BODY)
bx = badge(1313, 1135, "PARTLY LIVE")
chips_right(bx - 10, 1134, ["Claude"])
arrow_v(735, 1205, 1233)

# ── 6. shared services ───────────────────────────────────────────────────────
rail(1310, "SHARED", "SERVICES")
rect(L, 1239, LW, 183)
t(158, 1264, "Shared Retrieval & Model Services", 19, INK, 700)
t(158, 1285, "One set of services behind every agent — no duplicated plumbing, one place to govern", 12, BODY)
services = [
    ("db", "Hybrid Retrieval", ["Graph traversal + full-text + vector search, merged and", "scored"], ["Neo4j"]),
    ("chat", "Answer Generation", ["Claude Sonnet, grounded strictly in retrieved evidence"], ["Claude Sonnet", "Azure AI Foundry"]),
    ("sliders", "Semantic Embeddings", ["text-embedding-3-large for meaning-based search"], ["Azure OpenAI"]),
]
for i, (ic, name, desc, techs) in enumerate(services):
    x = 156 + i * 391
    rect(x, 1302, 372, 99, fill=SOFT, rx=8)
    icon(ic, x + 27, 1327, MUTED, 0.85)
    t(x + 49, 1325, name, 14.5, INK, 700)
    for j, line in enumerate(desc):
        t(x + 49, 1344 + j * 14, line, 10.5, "#475569")
    chips_left(x + 15, 1367, techs)

# shared services ↔ data
arrow_v(538, 1432, 1502)
t(548, 1464, "reads history · writes turns", 10.5, FAINT)
add(f'<line x1="1154" y1="1504" x2="1154" y2="1434" stroke="{ARROW}" stroke-width="2" marker-end="url(#arrow)"/>')
t(1163, 1464, "evidence, entities & source documents", 10.5, FAINT)

# ── 7. ingestion (right column) ──────────────────────────────────────────────
IX, IW = 1385, 584
rect(IX, 115, IW, 1307, fill="#fffdf5", stroke=AMBER, rx=18, dash="12,8", sw=2)
icon("docs", 1425, 150, "#b45309")
t(1456, 151, "Data Ingestion Pipeline", 20, AMBER_DK, 700)
badge(1944, 133, "OFFLINE · SEPARATE SERVICE")
t(1411, 180, "A standalone service that builds and refreshes the knowledge base. It is not", 12.5, "#475569")
t(1411, 198, "part of the live request path — the agents only ever read what it publishes.", 12.5, "#475569")
rect(1411, 232, 533, 290, fill=SOFT, rx=8)
t(1429, 261, "Why it sits outside the chat flow", 14.5, INK, 700)
for j, s in enumerate(["Runs on a schedule or on demand — no effect on chat response times",
                       "Can be re-run or extended without touching the live service",
                       "Every refresh will be validated before it goes live (planned)",
                       "Agents read the knowledge base; they never call this pipeline",
                       "Original documents are linked for reference only, never parsed live"]):
    y = 292 + j * 43
    add(f'<circle cx="1435" cy="{y - 4}" r="2" fill="{BODY}"/>')
    t(1445, y, s, 11.5, BODY)
stages = [("Read Source Documents", "Policies, standards & PRA reference material", ["Python"], None),
          ("AI-Powered Extraction", "Identifies domains, functions, rules & relationships", ["Claude", "Azure OpenAI"], None),
          ("Validate Before Publishing", "Quality and consistency checks on every run", ["Python"], "PLANNED"),
          ("Update Knowledge Base", "Graph updated; every fact keeps its source document", ["Neo4j"], None)]
for i, (name, desc, techs, status) in enumerate(stages):
    y = 593 + i * 195
    rect(1411, y, 533, 157, fill=AMBER_BG, stroke=AMBER_LINE, rx=8)
    t(1429, y + 30, name, 15, AMBER_DK, 700)
    if status:
        badge(1926, y + 15, status)
    t(1429, y + 57, desc, 11, AMBER_SUB)
    chips_left(1429, y + 101, techs)
    if i < 3:
        add(f'<line x1="1678" y1="{y + 165}" x2="1678" y2="{y + 187}" stroke="#c8961e" stroke-width="2" marker-end="url(#amber)"/>')
add('<line x1="1678" y1="1352" x2="1678" y2="1502" stroke="#c8961e" stroke-width="2.4" marker-end="url(#amber)"/>')
t(1696, 1444, "writes & refreshes", 11.5, AMBER_DK, 700)
t(1696, 1462, "the knowledge graph", 11.5, AMBER_DK, 700)

# ── 8. knowledge & data ──────────────────────────────────────────────────────
rail(1600, "KNOWLEDGE", "& DATA")
rect(131, 1508, 823, 206, fill=SOFT, rx=10)
icon("db", 175, 1545, MUTED, 1.1)
t(205, 1540, "Conversation History", 21, INK, 700)
t(205, 1562, "Secure record of every session, turn and retrieval", 12.5, BODY)
for j, s in enumerate(["Enables follow-ups and hand-offs between agents",
                       "Full audit trail of what was asked, retrieved and answered",
                       "Entity cache for fast PRA name matching"]):
    y = 1596 + j * 23
    add(f'<circle cx="164" cy="{y - 4}" r="2" fill="{BODY}"/>')
    t(174, y, s, 12, BODY)
chips_left(159, 1669, ["PostgreSQL", "SQLAlchemy async"])

rect(1000, 1508, 969, 206, fill="url(#kg)", stroke="#0b4fb0", rx=10)
icon("hub", 1044, 1545, "#ffffff", 1.0)
t(1074, 1540, "PRA Knowledge Graph", 21, "#ffffff", 700)
t(1074, 1562, "The organisation's payment domain expertise — 846 nodes, structured & connected", 12.5, "#dbeafe")
for j, s in enumerate(["Domains, functions, rules, patterns & anti-patterns — all linked",
                       "The single source of truth every agent reads from",
                       "Full-text index + vector search; every fact traceable to its source document"]):
    y = 1596 + j * 23
    add(f'<circle cx="1033" cy="{y - 4}" r="2" fill="#ffffff"/>')
    t(1043, y, s, 12, "#ffffff")
chips_left(1028, 1669, ["Neo4j", "Cypher + Lucene full-text"], on_dark=True)

# ── footer ───────────────────────────────────────────────────────────────────
add(f'<line x1="34" y1="1752" x2="1969" y2="1752" stroke="{LINE}"/>')
t(34, 1777, "Two-way arrows = live request & response flow   ·   Amber = offline ingestion (independent of chat)   ·   "
            "LIVE NOW = running today   ·   PARTLY LIVE = partly running   ·   PLANNED = designed, not yet built   ·   "
            "All services run within the enterprise network", 10.5, FAINT)
t(1969, 1777, "v5.1  ·  October 2026", 10.5, FAINT, anchor="end")

add("</svg>")
from pathlib import Path
target = sys.argv[1] if len(sys.argv) > 1 else Path(__file__).with_name("PRA_Chatbot_Architecture.svg")
open(target, "w", encoding="utf-8", newline="\r\n").write("\n".join(out) + "\n")
print("written", target)
