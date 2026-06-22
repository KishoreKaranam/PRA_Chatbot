"""
PRA Chatbot – Streamlit Frontend
Modern chatbot UI with settings panel collapsed at the sidebar bottom.
"""
import os
import httpx
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="PRA Chatbot",
    page_icon="💳",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Global ── */
[data-testid="stAppViewContainer"] { background: #f5f7fa; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: #1a1f2e !important;
    border-right: 1px solid #2d3548;
}
[data-testid="stSidebar"] * { color: #cdd6f4 !important; }
[data-testid="stSidebar"] .stSelectbox label,
[data-testid="stSidebar"] .stTextArea label,
[data-testid="stSidebar"] .stSlider label,
[data-testid="stSidebar"] .stToggle label {
    color: #a6adc8 !important;
    font-size: 0.82rem !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] {
    background: #252b3b !important;
    border: 1px solid #2d3548 !important;
    border-radius: 8px !important;
}
[data-testid="stSidebar"] hr { border-color: #2d3548 !important; }

/* ── Header bar ── */
.pra-header {
    background: linear-gradient(135deg, #1a1f2e 0%, #2d3a5e 100%);
    padding: 18px 28px 14px 28px;
    border-radius: 12px;
    margin-bottom: 18px;
    display: flex;
    align-items: center;
    gap: 14px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.12);
}
.pra-header-icon  { font-size: 2.2rem; }
.pra-header-title { font-size: 1.45rem; font-weight: 700; color: #ffffff; margin: 0; line-height: 1.2; }
.pra-header-sub   { font-size: 0.8rem; color: #89b4fa; margin: 2px 0 0 0; }

/* ── Chat bubbles ── */
.msg-row-user      { display:flex; justify-content:flex-end;  margin:10px 0; animation:fadeUp 0.2s ease; }
.msg-row-assistant { display:flex; justify-content:flex-start; margin:10px 0; animation:fadeUp 0.2s ease; }
.bubble-user {
    background: linear-gradient(135deg, #4f86f7 0%, #1a56db 100%);
    color: #ffffff !important;
    padding: 12px 16px;
    border-radius: 18px 18px 4px 18px;
    max-width: 72%;
    font-size: 0.93rem; line-height: 1.5;
    box-shadow: 0 2px 6px rgba(79,134,247,0.3);
    word-wrap: break-word;
}
.bubble-assistant {
    background: #ffffff;
    color: #1e1e2e !important;
    padding: 14px 18px;
    border-radius: 18px 18px 18px 4px;
    max-width: 78%;
    font-size: 0.93rem; line-height: 1.6;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    border: 1px solid #e8eaf0;
    word-wrap: break-word;
}
.avatar { width:32px; height:32px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:1rem; flex-shrink:0; margin-top:4px; }
.avatar-user { background:#4f86f7; margin-left:8px; }
.avatar-bot  { background:#1a1f2e; margin-right:8px; }

/* ── Confidence / badges ── */
.warning-inline { background:#fff8e1; border-left:3px solid #f59e0b; padding:6px 10px; border-radius:4px; font-size:0.82rem; color:#92400e; margin-bottom:6px; }
.mode-badges { margin-top:8px; }
.mode-badge  { background:#eff6ff; border:1px solid #bfdbfe; border-radius:10px; padding:1px 9px; font-size:0.75rem; color:#1d4ed8; margin-right:4px; }
.conf-bar-wrap { margin-top:6px; font-size:0.75rem; color:#6b7280; }

/* ── Empty state ── */
.empty-state { text-align:center; padding:60px 20px; color:#9ca3af; }
.empty-state .big-icon { font-size:3.5rem; margin-bottom:12px; }
.empty-state p { font-size:0.9rem; margin:4px 0; }
.empty-hints { display:flex; flex-wrap:wrap; gap:8px; justify-content:center; margin-top:18px; }
.hint-chip   { background:#ffffff; border:1px solid #e5e7eb; border-radius:20px; padding:6px 14px; font-size:0.82rem; color:#374151; }

/* ── Sidebar brand ── */
.sidebar-brand { text-align:center; padding:20px 0 8px 0; border-bottom:1px solid #2d3548; margin-bottom:8px; }
.sidebar-brand .brand-icon  { font-size:2.4rem; }
.sidebar-brand .brand-title { font-size:1rem; font-weight:700; color:#cdd6f4 !important; margin:4px 0 0 0; }
.sidebar-brand .brand-sub   { font-size:0.72rem; color:#6c7086 !important; }

/* ── Status pill ── */
.status-pill { display:inline-flex; align-items:center; gap:5px; padding:3px 10px; border-radius:12px; font-size:0.75rem; font-weight:500; }
.status-ok  { background:#1e3a2f; color:#4ade80 !important; }
.status-err { background:#3b1f1f; color:#f87171 !important; }

@keyframes fadeUp { from{opacity:0;transform:translateY(8px)} to{opacity:1;transform:translateY(0)} }
</style>
""", unsafe_allow_html=True)


# ── API helpers ───────────────────────────────────────────────────────────────

def fetch_instructions() -> dict:
    try:
        resp = httpx.get(f"{BACKEND_URL}/api/config/instructions", timeout=5)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {}


def save_instructions(data: dict) -> dict:
    try:
        resp = httpx.put(f"{BACKEND_URL}/api/config/instructions", json=data, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        st.error(f"Failed to save: {exc}")
        return data


def reset_instructions() -> dict:
    try:
        resp = httpx.post(f"{BACKEND_URL}/api/config/instructions/reset", timeout=5)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        st.error(f"Failed to reset: {exc}")
        return {}


def send_question(question: str, instructions: dict) -> dict:
    payload = {"question": question, "agent_instructions": instructions if instructions else None}
    resp = httpx.post(f"{BACKEND_URL}/api/chat", json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()


def get_health() -> dict:
    try:
        return httpx.get(f"{BACKEND_URL}/api/health", timeout=3).json()
    except Exception:
        return {}


def shorten_uri(uri: str, max_len: int = 55) -> str:
    if len(uri) <= max_len:
        return uri
    if "#" in uri:
        return "…#" + uri.split("#")[-1]
    if "/" in uri:
        return "…/" + uri.split("/")[-1]
    return uri[-max_len:]


# ── Session state ─────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "instructions" not in st.session_state:
    st.session_state.instructions = fetch_instructions()


# ══════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════
with st.sidebar:

    # Brand
    st.markdown("""
    <div class="sidebar-brand">
        <div class="brand-icon">💳</div>
        <div class="brand-title">PRA Chatbot</div>
        <div class="brand-sub">Payment Reference Architecture</div>
    </div>
    """, unsafe_allow_html=True)

    # Health status
    health = get_health()
    if health.get("graphdb_connected"):
        st.markdown(
            f'<span class="status-pill status-ok">● GraphDB · {health.get("repository","?")}</span>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<span class="status-pill status-err">● Backend unreachable</span>',
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # Clear chat
    if st.button("🗑️  Clear Chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

    # Push settings to bottom
    st.markdown("<div style='min-height:40px'></div>", unsafe_allow_html=True)
    st.markdown("---")

    # Settings collapsed at bottom
    with st.expander("⚙️  Settings & Instructions", expanded=False):
        instr = st.session_state.instructions

        system_prompt = st.text_area(
            "System Prompt",
            value=instr.get("system_prompt", ""),
            height=100,
            help="Defines the assistant's persona and constraints.",
        )

        retrieval_strategy = st.selectbox(
            "Retrieval Strategy",
            options=["hybrid", "sparql", "fts", "similarity"],
            index=["hybrid", "sparql", "fts", "similarity"].index(
                instr.get("retrieval_strategy", "hybrid")
            ),
            help="hybrid = all modes | sparql = graph | fts = text | similarity = vector",
        )

        answer_style = st.selectbox(
            "Answer Style",
            options=["business", "technical", "concise", "detailed"],
            index=["business", "technical", "concise", "detailed"].index(
                instr.get("answer_style", "business")
            ),
        )

        strict_mode = st.toggle(
            "Strict Ontology Mode",
            value=bool(instr.get("strict_ontology_mode", False)),
        )

        confidence_threshold = st.slider(
            "Confidence Threshold",
            min_value=0.0, max_value=1.0,
            value=float(instr.get("confidence_threshold", 0.3)),
            step=0.05,
        )

        max_results = st.slider(
            "Max Results",
            min_value=1, max_value=50,
            value=int(instr.get("max_results", 10)),
            step=1,
        )

        show_sparql_setting = st.toggle(
            "Show SPARQL Queries",
            value=bool(instr.get("show_sparql_queries", True)),
        )
        show_evidence_setting = st.toggle(
            "Show Source Evidence",
            value=bool(instr.get("show_raw_evidence", True)),
        )

        c1, c2 = st.columns(2)
        with c1:
            if st.button("💾 Save", use_container_width=True, key="save_btn"):
                updated = {
                    "system_prompt": system_prompt,
                    "retrieval_strategy": retrieval_strategy,
                    "answer_style": answer_style,
                    "strict_ontology_mode": strict_mode,
                    "confidence_threshold": confidence_threshold,
                    "max_results": max_results,
                    "show_sparql_queries": show_sparql_setting,
                    "show_raw_evidence": show_evidence_setting,
                }
                st.session_state.instructions = save_instructions(updated)
                st.success("✅ Saved")
        with c2:
            if st.button("↺ Reset", use_container_width=True, key="reset_btn"):
                st.session_state.instructions = reset_instructions()
                st.rerun()

    st.markdown(
        f"<div style='text-align:center;margin-top:8px;font-size:0.7rem;color:#45475a;'>"
        f"<a href='{BACKEND_URL}/docs' target='_blank' style='color:#45475a;text-decoration:none;'>API Docs ↗</a>"
        f"</div>",
        unsafe_allow_html=True,
    )

# Live settings from session
_instr             = st.session_state.instructions
show_sparql        = _instr.get("show_sparql_queries", True)
show_evidence_flag = _instr.get("show_raw_evidence", True)


# ══════════════════════════════════════════════════════════════════
# MAIN CHAT AREA
# ══════════════════════════════════════════════════════════════════

st.markdown("""
<div class="pra-header">
    <div class="pra-header-icon">💳</div>
    <div>
        <p class="pra-header-title">Payment Reference Architecture Chatbot</p>
        <p class="pra-header-sub">
            Ask about business functions, rules, activities, domains, schemes and more —
            grounded in the PRA knowledge graph.
        </p>
    </div>
</div>
""", unsafe_allow_html=True)


def render_evidence_expander(evidence: list) -> None:
    if not evidence or not show_evidence_flag:
        return
    with st.expander("📋 Source Evidence", expanded=False):
        for ev in evidence:
            mode = ev.get("mode", "unknown")
            st.markdown(f"#### Mode: `{mode}`")
            if mode == "sparql":
                if show_sparql:
                    st.code(ev.get("query", ""), language="sparql")
                triples = ev.get("triples", [])
                st.caption(f"{len(triples)} triples retrieved")
                for t in triples[:25]:
                    s = shorten_uri(t.get("subject", ""))
                    p = shorten_uri(t.get("predicate", ""))
                    o = shorten_uri(t.get("obj", ""))
                    st.markdown(f"- `{s}` → `{p}` → `{o}`")
                if len(triples) > 25:
                    st.caption(f"… and {len(triples) - 25} more triples")
            elif mode == "fts":
                st.markdown(f"**Search term:** `{ev.get('search_term','')}`")
                for hit in ev.get("hits", []):
                    st.markdown(
                        f"- **{hit.get('label','')}** (score: {hit.get('score',0):.3f})  \n"
                        f"  _{hit.get('snippet','')[:200]}_"
                    )
            elif mode == "similarity":
                note = ev.get("note", "")
                if note:
                    st.info(note)
                for hit in ev.get("hits", []):
                    st.markdown(
                        f"- **{hit.get('label','')}** (similarity: {hit.get('score',0):.3f})  \n"
                        f"  _{hit.get('text','')[:200]}_"
                    )
            st.divider()


def render_assistant_bubble(msg: dict) -> None:
    answer     = msg.get("answer", "")
    modes      = msg.get("retrieval_modes_used", [])
    evidence   = msg.get("evidence", [])
    confidence = msg.get("confidence")
    warning    = msg.get("warning")

    warning_html = f'<div class="warning-inline">⚠️ {warning}</div>' if warning else ""

    badges_html = ""
    if modes:
        badges = "".join(f'<span class="mode-badge">🔍 {m}</span>' for m in modes)
        badges_html = f'<div class="mode-badges">{badges}</div>'

    conf_html = ""
    if confidence is not None:
        pct = int(confidence * 100)
        color = "#4ade80" if pct >= 70 else "#facc15" if pct >= 40 else "#f87171"
        conf_html = (
            f'<div class="conf-bar-wrap">'
            f'<span style="color:{color}">■</span> '
            f'Evidence confidence: <strong>{pct}%</strong></div>'
        )

    st.markdown(
        f'<div class="msg-row-assistant">'
        f'<div class="avatar avatar-bot">🤖</div>'
        f'<div class="bubble-assistant">{warning_html}{answer}{badges_html}{conf_html}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    render_evidence_expander(evidence)


# ── Chat history ──────────────────────────────────────────────────
if not st.session_state.messages:
    st.markdown("""
    <div class="empty-state">
        <div class="big-icon">💬</div>
        <p><strong>Ask anything about the Payment Reference Architecture</strong></p>
        <p>Answers are grounded in SPARQL graph queries, full-text search, and semantic similarity.</p>
        <div class="empty-hints">
            <span class="hint-chip">What are business functions?</span>
            <span class="hint-chip">List payment journey functions</span>
            <span class="hint-chip">What rules govern payment capture?</span>
            <span class="hint-chip">What activities does authentication have?</span>
            <span class="hint-chip">Explain information objects</span>
        </div>
    </div>
    """, unsafe_allow_html=True)
else:
    for msg in st.session_state.messages:
        if msg["role"] == "user":
            st.markdown(
                f'<div class="msg-row-user">'
                f'<div class="bubble-user">{msg["content"]}</div>'
                f'<div class="avatar avatar-user">🧑</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            render_assistant_bubble(msg)


# ── Chat input ────────────────────────────────────────────────────
if prompt := st.chat_input("Ask about payment domains, business functions, rules, schemes…"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.markdown(
        f'<div class="msg-row-user">'
        f'<div class="bubble-user">{prompt}</div>'
        f'<div class="avatar avatar-user">🧑</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    with st.spinner("Searching the knowledge graph…"):
        try:
            result = send_question(prompt, st.session_state.instructions)
            result["role"] = "assistant"
            st.session_state.messages.append(result)
            render_assistant_bubble(result)
        except httpx.ConnectError:
            st.error(f"⚠️ Cannot reach the backend at {BACKEND_URL}. Is the FastAPI server running?")
        except httpx.HTTPStatusError as exc:
            st.error(f"Backend error {exc.response.status_code}: {exc.response.text[:300]}")
        except Exception as exc:
            st.error(f"Unexpected error: {exc}")
