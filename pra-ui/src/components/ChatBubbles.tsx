import { useState } from "react";
import { Copy, Check } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatResponse } from "../api";
import { EvidencePanel } from "./EvidencePanel";

interface UserBubbleProps { text: string; }
interface BotBubbleProps { msg: ChatResponse; showSparql: boolean; showEvidence: boolean; }

export function UserBubble({ text }: UserBubbleProps) {
  return (
    <div className="message-row message-row--user">
      <div className="bubble bubble--user">{text}</div>
      <div className="message-avatar message-avatar--user">👤</div>
    </div>
  );
}

export function BotBubble({ msg, showSparql, showEvidence }: BotBubbleProps) {
  const [copied, setCopied] = useState(false);
  const pct = Math.round((msg.confidence ?? 0) * 100);
  const confColor = pct >= 70 ? "var(--success)" : pct >= 40 ? "var(--warning)" : "var(--danger)";

  const handleCopy = async () => {
    await navigator.clipboard.writeText(msg.answer);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="message-row message-row--bot">
      <div className="message-avatar message-avatar--bot">🤖</div>
      <div style={{ maxWidth: "78%", minWidth: 0 }}>
        <div className="bubble bubble--bot">
          {msg.warning && <div className="warning-banner">⚠️ {msg.warning}</div>}
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.answer}</ReactMarkdown>
          <div className="message-meta">
            {msg.retrieval_modes_used?.length > 0 && msg.retrieval_modes_used.map((m) => (
              <span key={m} className="mode-badge">{m === "sparql" ? "🔗" : m === "fts" ? "🔍" : "🧠"} {m}</span>
            ))}
            <div className="confidence-bar">
              <div className="confidence-bar__track">
                <div className="confidence-bar__fill" style={{ width: `${pct}%`, background: confColor }} />
              </div>
              <span>{pct}%</span>
            </div>
            <button className="copy-btn" onClick={handleCopy} title="Copy answer">
              {copied ? <><Check size={12} /> Copied</> : <><Copy size={12} /> Copy</>}
            </button>
          </div>
        </div>
        {showEvidence && <EvidencePanel evidence={msg.evidence} showSparql={showSparql} />}
      </div>
    </div>
  );
}
