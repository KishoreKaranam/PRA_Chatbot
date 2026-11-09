import { Children, cloneElement, isValidElement, memo, useMemo, useState } from "react";
import type { ReactElement, ReactNode } from "react";
import { Copy, Check, HelpCircle, RotateCcw, FileText, AlertTriangle } from "lucide-react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatResponse } from "../api";
import { MermaidDiagram } from "./MermaidDiagram";
import { buildChipLayout, shortDocName, warningsInRange } from "./inlineSources";
import type { ChipGroup, ChipLayout, Claim } from "./inlineSources";

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


// ── Inline source chips (next to each paragraph / bullet / table row) ─────────

function claimList(claims: string[]): string {
  return claims.map((c) => `• ${c}`).join("\n");
}

function covers(lines: string[], lineCount: number): string {
  const head = lineCount > 1 ? `Supports these ${lineCount} lines:` : "Supports:";
  return `${head}\n${claimList(lines)}`;
}

// One row of chips for a group of consecutive lines that share the same documents.
function InlineSources({ group, block }: { group: ChipGroup; block?: boolean }) {
  const { docs, supported, kb, unsupported, lineCount } = group;
  if (docs.length === 0 && kb.length === 0 && unsupported.length === 0) return null;
  return (
    <span className={`inline-sources${block ? " inline-sources--block" : ""}`}>
      {block && (docs.length > 0 || kb.length > 0) && <span className="inline-sources__label">Sources</span>}
      {docs.map((doc) =>
        doc.url ? (
          <a
            key={doc.name}
            className="inline-source"
            href={doc.url}
            target="_blank"
            rel="noopener noreferrer"
            title={`${doc.name}\n\n${covers(supported, lineCount)}`}
          >
            <FileText size={10} /> {shortDocName(doc.name)}
          </a>
        ) : (
          <span
            key={doc.name}
            className="inline-source inline-source--nolink"
            title={`${doc.name} (no PDF copy)\n\n${covers(supported, lineCount)}`}
          >
            <FileText size={10} /> {shortDocName(doc.name)}
          </span>
        ),
      )}
      {docs.length === 0 && kb.length > 0 && (
        <span className="inline-source inline-source--nolink" title={`Found in the PRA knowledge base:\n${claimList(kb)}`}>
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

  // Source chips are added as soon as the evidence check arrives.
  // While the check runs, the backend sends the lines checked so far
  // (method "partial"): their chips appear right away, the % comes at the end.
  const partial = msg.grounding?.method === "partial";
  const reviewing = (Boolean(msg.reviewing) && !msg.grounding) || (partial && Boolean(streaming));
  // Chips appear while the answer is written (from `sources_map`), are confirmed
  // or flagged by the evidence check, and are grouped per block by source.
  const checked = !!msg.grounding && msg.grounding.method !== "none";
  const answerComplete = !streaming || Boolean(msg.reviewing) || !!msg.grounding;
  const layout: ChipLayout = useMemo(
    () => isClarification ? { anchors: new Map(), warnings: new Map() } : buildChipLayout(msg.answer, {
      claims: checked ? (msg.grounding!.claims as Claim[]) : undefined,
      sources: msg.sources_map ?? null,
      complete: answerComplete,
    }),
    [isClarification, msg.answer, msg.grounding, checked, msg.sources_map, answerComplete],
  );
  const EMPTY: ChipGroup = { docs: [], supported: [], kb: [], unsupported: [], lineCount: 0 };
  // "Not in sources" on exactly the lines it concerns.
  const warningsFor = (node: HastNode | undefined, endLine?: number) => {
    if (!node?.position) return null;
    const w = warningsInRange(layout, node.position.start.line, endLine ?? node.position.end.line);
    return w.length ? <InlineSources group={{ ...EMPTY, unsupported: w }} /> : null;
  };
  // Source chips of a block that ends here (paragraph: inline; list/table/diagram: row below).
  const blockChips = (node: HastNode | undefined, kinds: string[], block: boolean) => {
    if (!node?.position) return null;
    const { start, end } = { start: node.position.start.line, end: node.position.end.line };
    for (let n = end; n >= start; n--) {
      const anchor = layout.anchors.get(n);
      // A list/table/diagram must be the outer block itself (not a nested list inside it).
      if (anchor && kinds.includes(anchor.kind) && (!block || anchor.start === start)) {
        return <InlineSources group={anchor.group} block={block} />;
      }
    }
    return null;
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
      if (isMermaid) return <>{children}{blockChips(node as HastNode, ["code"], true)}</>;
      return <pre>{children}</pre>;
    },
    p({ node, children }) {
      return <p>{children}{warningsFor(node as HastNode)}{blockChips(node as HastNode, ["paragraph"], false)}</p>;
    },
    ul({ node, children }) {
      return <><ul>{children}</ul>{blockChips(node as HastNode, ["list"], true)}</>;
    },
    ol({ node, children, start }) {
      return <><ol start={start}>{children}</ol>{blockChips(node as HastNode, ["list"], true)}</>;
    },
    table({ node, children }) {
      return <><table>{children}</table>{blockChips(node as HastNode, ["table"], true)}</>;
    },
    li({ node, children, className }) {
      const n = node as HastNode;
      const kids = n?.children ?? [];
      // In "loose" lists the text sits in a <p>, which shows the chips itself.
      if (kids.some((k) => k.tagName === "p")) return <li className={className}>{children}</li>;
      // Only this item's own lines, not its nested sub-list; chips go before the sub-list.
      const nested = kids.find((k) => k.tagName === "ul" || k.tagName === "ol");
      const end = nested?.position ? nested.position.start.line - 1 : undefined;
      const chips = warningsFor(n, end);
      if (!chips) return <li className={className}>{children}</li>;
      const items = Children.toArray(children);
      const at = items.findIndex((c) => isValidElement(c) && (c.type === "ul" || c.type === "ol"));
      if (at === -1) return <li className={className}>{items}{chips}</li>;
      return <li className={className}>{items.slice(0, at)}{chips}{items.slice(at)}</li>;
    },
    tr({ node, children }) {
      const chips = warningsFor(node as HastNode);
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
          {streaming && !reviewing && !msg.grounding && !isClarification && <span className="streaming-cursor" aria-hidden="true" />}

          {/* ── Meta row (copy) ─────────────────────────────────────────── */}
          {!isClarification && (
            <div className="message-meta">
              <button className="copy-btn" onClick={handleCopy} title="Copy answer">
                {copied ? <><Check size={12} /> Copied</> : <><Copy size={12} /> Copy</>}
              </button>
            </div>
          )}
        </div>

        
      </div>
    </div>
  );
});
