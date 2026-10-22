import { Children, cloneElement, isValidElement, memo, useMemo, useState } from "react";
import type { ReactElement, ReactNode } from "react";
import { Copy, Check, HelpCircle, RotateCcw, ShieldCheck, ChevronDown, FileText, AlertTriangle } from "lucide-react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatResponse } from "../api";
import type { DocumentRef, GroundingReport } from "../api";
import { MermaidDiagram } from "./MermaidDiagram";
import { claimsByLine, claimsInRange, groupSources, shortDocName } from "./inlineSources";
import type { Claim } from "./inlineSources";

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

// Links to the source documents (PDF copies) behind a claim. A document with
// no PDF copy is shown as plain text so the user still sees where it came from.
function SourceLinks({ sources }: { sources?: DocumentRef[] }) {
  if (!sources || sources.length === 0) return null;
  return (
    <span className="grounding__sources">
      {sources.map((doc) =>
        doc.url ? (
          <a
            key={doc.name}
            className="grounding__source"
            href={doc.url}
            target="_blank"
            rel="noopener noreferrer"
            title={`Open ${doc.name} (PDF)`}
          >
            <FileText size={11} /> {doc.name}
          </a>
        ) : (
          <span
            key={doc.name}
            className="grounding__source grounding__source--nolink"
            title="No PDF copy available"
          >
            <FileText size={11} /> {doc.name}
          </span>
        ),
      )}
    </span>
  );
}

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
                  <span className="grounding__claim">
                    <span>{c.claim}</span>
                    <SourceLinks sources={c.sources} />
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

// ── Inline source chips (next to each paragraph / bullet / table row) ─────────

function claimList(claims: string[]): string {
  return claims.map((c) => `• ${c}`).join("\n");
}

function InlineSources({ claims, block }: { claims: Claim[]; block?: boolean }) {
  if (claims.length === 0) return null;
  const { docs, verifiedNoDoc, unsupported } = groupSources(claims);
  if (docs.length === 0 && verifiedNoDoc.length === 0 && unsupported.length === 0) return null;
  return (
    <span className={`inline-sources${block ? " inline-sources--block" : ""}`}>
      {docs.map(({ doc, claims: supported }) =>
        doc.url ? (
          <a
            key={doc.name}
            className="inline-source"
            href={doc.url}
            target="_blank"
            rel="noopener noreferrer"
            title={`${doc.name}\n\nSupports:\n${claimList(supported)}`}
          >
            <FileText size={10} /> {shortDocName(doc.name)}
          </a>
        ) : (
          <span
            key={doc.name}
            className="inline-source inline-source--nolink"
            title={`${doc.name} (no PDF copy)\n\nSupports:\n${claimList(supported)}`}
          >
            <FileText size={10} /> {shortDocName(doc.name)}
          </span>
        ),
      )}
      {docs.length === 0 && verifiedNoDoc.length > 0 && (
        <span className="inline-source inline-source--nolink" title={`Found in the PRA knowledge base:\n${claimList(verifiedNoDoc)}`}>
          <Check size={10} /> PRA knowledge base
        </span>
      )}
      {unsupported.length > 0 && (
        <span className="inline-source inline-source--warn" title={`Not found in the sources:\n${claimList(unsupported)}`}>
          <AlertTriangle size={10} /> Not in sources
        </span>
      )}
    </span>
  );
}

type HastNode = { type?: string; tagName?: string; position?: { start: { line: number }; end: { line: number } }; children?: HastNode[] };

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

  // Source chips are added once the evidence check has finished.
  const showInline =
    !streaming && !isClarification && !!msg.grounding && msg.grounding.method !== "none";
  const byLine = useMemo(
    () => (showInline && msg.grounding ? claimsByLine(msg.answer, msg.grounding.claims as Claim[]) : new Map<number, Claim[]>()),
    [showInline, msg.answer, msg.grounding],
  );
  const chipsFor = (node: HastNode | undefined, endLine?: number, block?: boolean) => {
    if (!showInline || !node?.position) return null;
    const claims = claimsInRange(byLine, node.position.start.line, endLine ?? node.position.end.line);
    return claims.length ? <InlineSources claims={claims} block={block} /> : null;
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
      if (isMermaid) return <>{children}{chipsFor(node as HastNode, undefined, true)}</>;
      return <pre>{children}</pre>;
    },
    p({ node, children }) {
      return <p>{children}{chipsFor(node as HastNode)}</p>;
    },
    li({ node, children, className }) {
      const n = node as HastNode;
      const kids = n?.children ?? [];
      // In "loose" lists the text sits in a <p>, which shows the chips itself.
      if (kids.some((k) => k.tagName === "p")) return <li className={className}>{children}</li>;
      // Only this item's own lines, not its nested sub-list; chips go before the sub-list.
      const nested = kids.find((k) => k.tagName === "ul" || k.tagName === "ol");
      const end = nested?.position ? nested.position.start.line - 1 : undefined;
      const chips = chipsFor(n, end);
      if (!chips) return <li className={className}>{children}</li>;
      const items = Children.toArray(children);
      const at = items.findIndex((c) => isValidElement(c) && (c.type === "ul" || c.type === "ol"));
      if (at === -1) return <li className={className}>{items}{chips}</li>;
      return <li className={className}>{items.slice(0, at)}{chips}{items.slice(at)}</li>;
    },
    tr({ node, children }) {
      const chips = chipsFor(node as HastNode);
      if (!chips) return <tr>{children}</tr>;
      const cells = Children.toArray(children).filter(isValidElement) as ReactElement<{ children?: ReactNode }>[];
      if (cells.length === 0) return <tr>{children}</tr>;
      const last = cells[cells.length - 1];
      return <tr>{cells.slice(0, -1)}{cloneElement(last, undefined, last.props.children, chips)}</tr>;
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
