import { useState } from "react";
import { Copy, Check, HelpCircle, RotateCcw } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatResponse } from "../api";
import { EvidencePanel } from "./EvidencePanel";

interface UserBubbleProps { text: string; }
interface BotBubbleProps { msg: ChatResponse; showQueries: boolean; showEvidence: boolean; }

// ── Intent badge ──────────────────────────────────────────────────────────────

const INTENT_CONFIG: Record<string, { label: string; emoji: string; cls: string }> = {
  definition:  { label: "Definition",  emoji: "📖", cls: "intent-badge--definition"  },
  list:        { label: "List",        emoji: "📋", cls: "intent-badge--list"        },
  comparison:  { label: "Comparison",  emoji: "⚖️", cls: "intent-badge--comparison"  },
  exploratory: { label: "Exploratory", emoji: "🔭", cls: "intent-badge--exploratory" },
  vague:       { label: "Clarifying",  emoji: "❓", cls: "intent-badge--vague"       },
};

function IntentBadge({ intent }: { intent: string }) {
  const cfg = INTENT_CONFIG[intent] ?? INTENT_CONFIG.exploratory;
  return (
    <span className={`intent-badge ${cfg.cls}`}>
      <span>{cfg.emoji}</span> {cfg.label}
    </span>
  );
}

// ── User bubble ───────────────────────────────────────────────────────────────

export function UserBubble({ text }: UserBubbleProps) {
  return (
    <div className="message-row message-row--user">
      <div className="bubble bubble--user">{text}</div>
      <div className="message-avatar message-avatar--user">👤</div>
    </div>
  );
}

// ── Bot bubble ────────────────────────────────────────────────────────────────

export function BotBubble({ msg, showQueries, showEvidence }: BotBubbleProps) {
  const [copied, setCopied] = useState(false);
  const pct = Math.round((msg.confidence ?? 0) * 100);
  const confColor = pct >= 70 ? "var(--success)" : pct >= 40 ? "var(--warning)" : "var(--danger)";
  const isClarification = Boolean(msg.clarification_needed);
  const rewrittenDiffers =
    msg.rewritten_question &&
    msg.rewritten_question.trim() !== "" &&
    msg.rewritten_question.trim() !== msg.question.trim();

  const handleCopy = async () => {
    await navigator.clipboard.writeText(msg.answer);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="message-row message-row--bot">
      <div className={`message-avatar message-avatar--bot${isClarification ? " message-avatar--clarify" : ""}`}>
        {isClarification ? <HelpCircle size={16} /> : "🤖"}
      </div>
      <div style={{ maxWidth: "78%", minWidth: 0 }}>

        {/* ── Intent badge + rewritten question ─────────────────────────── */}
        {(msg.intent || rewrittenDiffers) && (
          <div className="bubble-meta-row">
            {msg.intent && <IntentBadge intent={msg.intent} />}
            {rewrittenDiffers && (
              <span className="rewritten-banner">
                <RotateCcw size={11} style={{ flexShrink: 0 }} />
                Interpreted as: <em>{msg.rewritten_question}</em>
              </span>
            )}
          </div>
        )}

        {/* ── Main bubble ────────────────────────────────────────────────── */}
        <div className={`bubble bubble--bot${isClarification ? " bubble--clarification" : ""}`}>
          {isClarification && (
            <div className="clarification-header">
              <HelpCircle size={14} />
              <span>I need a bit more context</span>
            </div>
          )}
          {msg.warning && !isClarification && (
            <div className="warning-banner">⚠️ {msg.warning}</div>
          )}
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.answer}</ReactMarkdown>

          {/* ── Meta row (modes + confidence + copy) ────────────────────── */}
          {!isClarification && (
            <div className="message-meta">
              {msg.retrieval_modes_used?.length > 0 && msg.retrieval_modes_used.map((m) => (
                <span key={m} className="mode-badge">
                  {m === "sparql" ? "🔗" : m === "fts" ? "🔍" : "🧠"} {m}
                </span>
              ))}
              {pct > 0 && (
                <div className="confidence-bar">
                  <div className="confidence-bar__track">
                    <div className="confidence-bar__fill" style={{ width: `${pct}%`, background: confColor }} />
                  </div>
                  <span>{pct}%</span>
                </div>
              )}
              <button className="copy-btn" onClick={handleCopy} title="Copy answer">
                {copied ? <><Check size={12} /> Copied</> : <><Copy size={12} /> Copy</>}
              </button>
            </div>
          )}
        </div>

        {showEvidence && !isClarification && (
          <EvidencePanel evidence={msg.evidence} showQueries={showQueries} />
        )}
      </div>
    </div>
  );
}
