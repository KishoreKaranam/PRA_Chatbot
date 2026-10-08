import { memo, useState } from "react";
import { Copy, Check, HelpCircle, RotateCcw, ShieldCheck, ChevronDown } from "lucide-react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatResponse } from "../api";
import type { GroundingReport } from "../api";
import { MermaidDiagram } from "./MermaidDiagram";

interface UserBubbleProps { text: string; }
interface BotBubbleProps { msg: ChatResponse; streaming?: boolean; }

// ── Intent badge ──────────────────────────────────────────────────────────────

const INTENT_CONFIG: Record<string, { label: string; emoji: string; cls: string }> = {
  definition:  { label: "Definition",  emoji: "📖", cls: "intent-badge--definition"  },
  list:        { label: "List",        emoji: "📋", cls: "intent-badge--list"        },
  comparison:  { label: "Comparison",  emoji: "⚖️", cls: "intent-badge--comparison"  },
  exploratory: { label: "Exploratory", emoji: "🔭", cls: "intent-badge--exploratory" },
  vague:       { label: "Clarifying",  emoji: "❓", cls: "intent-badge--vague"       },
  diagram:     { label: "Diagram",     emoji: "📊", cls: "intent-badge--diagram"     },
};

function IntentBadge({ intent }: { intent: string }) {
  const cfg = INTENT_CONFIG[intent] ?? INTENT_CONFIG.exploratory;
  return (
    <span className={`intent-badge ${cfg.cls}`}>
      <span>{cfg.emoji}</span> {cfg.label}
    </span>
  );
}

// ── Grounding / output review badge ─────────────────────────────────────────

const GROUNDING_CONFIG: Record<string, { label: string; color: string }> = {
  high:       { label: "Well grounded",   color: "#16a34a" },
  moderate:   { label: "Partly grounded", color: "#d97706" },
  low:        { label: "Weakly grounded", color: "#dc2626" },
  unverified: { label: "Unverified",      color: "#6b7280" },
};

function GroundingBadge({ report }: { report: GroundingReport }) {
  const [open, setOpen] = useState(false);
  const cfg = GROUNDING_CONFIG[report.verdict] ?? GROUNDING_CONFIG.unverified;
  const pct = Math.round(report.grounded_percentage);

  return (
    <div className="grounding">
      <button
        className="grounding__badge"
        onClick={() => setOpen((o) => !o)}
        title={report.summary}
        style={{ ["--grounding-color" as string]: cfg.color }}
      >
        <ShieldCheck size={12} />
        <span className="grounding__pct">{pct}% evidence-based</span>
        <span className="grounding__verdict">· {cfg.label}</span>
        <span className="grounding__track">
          <span className="grounding__fill" style={{ width: `${pct}%`, background: cfg.color }} />
        </span>
        <ChevronDown
          size={12}
          style={{ transform: open ? "rotate(180deg)" : "none", transition: "transform .2s" }}
        />
      </button>

      {open && (
        <div className="grounding__details">
          {report.summary && <p className="grounding__summary">{report.summary}</p>}
          <p className="grounding__stat">
            {report.supported_claims} of {report.total_claims} claims supported
            {report.method === "lexical" && " · estimated"}
          </p>
          {report.claims.length > 0 && (
            <ul className="grounding__claims">
              {report.claims.map((c, i) => (
                <li key={i} className={c.supported ? "is-supported" : "is-unsupported"}>
                  <span className="grounding__mark">{c.supported ? "✓" : "✕"}</span>
                  <span>{c.claim}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

// ── User bubble ───────────────────────────────────────────────────────────────

export const UserBubble = memo(function UserBubble({ text }: UserBubbleProps) {
  return (
    <div className="message-row message-row--user">
      <div className="bubble bubble--user">{text}</div>
      <div className="message-avatar message-avatar--user">👤</div>
    </div>
  );
});

// ── Bot bubble ────────────────────────────────────────────────────────────────

export const BotBubble = memo(function BotBubble({ msg, streaming }: BotBubbleProps) {
  const [copied, setCopied] = useState(false);
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

  // Render ```mermaid fenced blocks as downloadable pictures; all other
  // code blocks fall through to the default rendering.
  const markdownComponents: Components = {
    // Unwrap the <pre> around a mermaid block so the rendered SVG <div> is not
    // invalidly nested inside a <pre>. Non-mermaid code keeps its <pre>.
    pre({ node, children }) {
      const child = node?.children?.[0];
      const cls =
        child && child.type === "element" ? child.properties?.className : undefined;
      const isMermaid = Array.isArray(cls) && cls.includes("language-mermaid");
      if (isMermaid) return <>{children}</>;
      return <pre>{children}</pre>;
    },
    code({ className, children, ...props }) {
      const match = /language-mermaid/.test(className || "");
      if (match) {
        return (
          <MermaidDiagram
            code={String(children).replace(/\n$/, "")}
            streaming={streaming}
          />
        );
      }
      return (
        <code className={className} {...props}>
          {children}
        </code>
      );
    },
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
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{msg.answer}</ReactMarkdown>
          {streaming && !isClarification && <span className="streaming-cursor" aria-hidden="true" />}

          {/* ── Meta row (copy) ─────────────────────────────────────────── */}
          {!isClarification && (
            <div className="message-meta">
              <button className="copy-btn" onClick={handleCopy} title="Copy answer">
                {copied ? <><Check size={12} /> Copied</> : <><Copy size={12} /> Copy</>}
              </button>
            </div>
          )}
        </div>

        {/* ── Output review: % grounded in evidence ───────────────────────── */}
        {!isClarification && !streaming && msg.grounding && msg.grounding.method !== "none" && (
          <GroundingBadge report={msg.grounding} />
        )}
      </div>
    </div>
  );
});
