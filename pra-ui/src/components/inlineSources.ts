// Places the evidence check's claims next to the part of the answer they came
// from, so source links can be shown inline (like ChatGPT) instead of only in
// the evidence panel at the bottom.
//
// The reviewer returns, for each claim, `answer_quote`: the exact sentence /
// bullet / table row of the answer it was taken from. We find the line of the
// answer's markdown that contains that quote. Older answers (saved before this
// change) have no quote, so we fall back to word overlap with the claim text.

import type { DocumentRef, GroundingClaim } from "../api";

export type Claim = GroundingClaim & { answer_quote?: string };

const STOP = new Set([
  "that", "this", "with", "from", "into", "they", "their", "them", "which", "where",
  "while", "when", "what", "have", "been", "also", "such", "than", "then", "these",
  "those", "each", "other", "within", "across", "including", "between", "about",
]);

function norm(text: string): string {
  return text
    .toLowerCase()
    .replace(/<br\s*\/?>/g, " ")
    .replace(/[^a-z0-9&]+/g, " ")
    .trim();
}

function words(text: string): string[] {
  return norm(text).split(" ").filter((w) => w.length >= 4 && !STOP.has(w));
}

/** Map each claim to the 1-based line of `answer` it most likely came from. */
export function claimsByLine(answer: string, claims: Claim[]): Map<number, Claim[]> {
  const lines = answer.split("\n").map(norm);
  const lineWords = lines.map((l) => new Set(l.split(" ")));
  const result = new Map<number, Claim[]>();

  for (const claim of claims) {
    const quote = norm(claim.answer_quote ?? "");
    let best = -1;
    let bestScore = 0;

    lines.forEach((line, i) => {
      if (!line) return;
      let score = 0;
      if (quote.length >= 12 && line.includes(quote)) score = 3;            // quote inside this line
      else if (quote.length >= 12 && line.length >= 12 && quote.includes(line)) score = 2; // quote spans lines
      else {
        const target = words(claim.answer_quote || claim.claim);
        if (target.length >= 2) {
          const hits = target.filter((w) => lineWords[i].has(w)).length;
          const overlap = hits / target.length;
          if (overlap >= 0.5) score = overlap;                              // 0.5 – 1.0
        }
      }
      if (score > bestScore) {
        bestScore = score;
        best = i;
      }
    });

    if (best >= 0) {
      const lineNo = best + 1;
      result.set(lineNo, [...(result.get(lineNo) ?? []), claim]);
    }
  }
  return result;
}

/** Claims placed on lines start..end (inclusive). */
export function claimsInRange(byLine: Map<number, Claim[]>, start?: number, end?: number): Claim[] {
  if (!start || !end) return [];
  const out: Claim[] = [];
  for (let line = start; line <= end; line++) out.push(...(byLine.get(line) ?? []));
  return out;
}

/** "PRA Functional descriptions for Payments Journey.xlsx" -> "Payments Journey". */
export function shortDocName(name: string): string {
  return (
    name
      .replace(/\.(pdf|docx?|xlsx?|pptx?|csv|txt)$/i, "")
      .replace(/^PRA\s+/i, "")
      .replace(/^Functional descriptions for\s+/i, "")
      .trim() || name
  );
}

export interface InlineSourceGroup {
  docs: { doc: DocumentRef; claims: string[] }[];
  verifiedNoDoc: string[];   // supported, but the evidence had no source document
  unsupported: string[];     // not found in the evidence
}

/** Group a block's claims by source document (each document shown once). */
export function groupSources(claims: Claim[]): InlineSourceGroup {
  const byDoc = new Map<string, { doc: DocumentRef; claims: string[] }>();
  const verifiedNoDoc: string[] = [];
  const unsupported: string[] = [];
  for (const c of claims) {
    if (!c.supported) {
      unsupported.push(c.claim);
      continue;
    }
    if (!c.sources || c.sources.length === 0) {
      verifiedNoDoc.push(c.claim);
      continue;
    }
    for (const doc of c.sources) {
      const entry = byDoc.get(doc.name) ?? { doc, claims: [] };
      entry.claims.push(c.claim);
      byDoc.set(doc.name, entry);
    }
  }
  return { docs: [...byDoc.values()], verifiedNoDoc, unsupported };
}

// ── Chips while the answer is written, grouped by source ─────────────────────
//
// 1. Instant: the backend sends `sources` = { PRA name -> its documents } at the
//    start of the answer. Every finished line gets the documents of the PRA
//    names it mentions, as soon as it is written.
// 2. Checked: once the evidence check has judged a line, its verdict replaces
//    the instant guess (unsupported lines get "Not in sources" instead).
// 3. Grouped per block: a paragraph gets one chip row at its end; a whole list,
//    table or diagram gets one row below it with every document it uses (most
//    used first). Consecutive blocks with the same documents share one row.
//    "Not in sources" warnings stay on the exact line they concern.

export type SourcesMap = Record<string, DocumentRef[]>;

export interface ChipGroup {
  docs: DocumentRef[];
  supported: string[];     // lines/claims these documents back (tooltip)
  kb: string[];            // checked, but the graph has no document for them
  unsupported: string[];   // not found in the evidence
  lineCount: number;
}

const MAX_DOCS_PER_LINE = 2;

function plainLine(line: string): string {
  return line
    .replace(/^\s*(?:[-*+]|\d+[.)])\s+/, "")
    .replace(/\*\*|__|`/g, "")
    .replace(/\s*\|\s*/g, " — ")
    .replace(/^ — | — $/g, "")
    .trim();
}

function matchKey(text: string): string {
  return ` ${text.toLowerCase().replace(/&/g, " and ").replace(/[^a-z0-9]+/g, " ").trim()} `;
}

/** Documents of the PRA names mentioned in a line (longest names first, most common docs first). */
export function docsForLine(line: string, sources: SourcesMap, names?: string[]): DocumentRef[] {
  let text = matchKey(line);
  const ordered = names ?? Object.keys(sources).sort((a, b) => b.length - a.length);
  const counts = new Map<string, { doc: DocumentRef; n: number; first: number }>();
  let order = 0;
  for (const name of ordered) {
    const key = matchKey(name);
    if (key.trim().length < 4 || !text.includes(key)) continue;
    text = text.split(key).join(" ");                 // a longer name hides the names inside it
    for (const doc of sources[name] ?? []) {
      const entry = counts.get(doc.name) ?? { doc, n: 0, first: order++ };
      entry.n += 1;
      counts.set(doc.name, entry);
    }
  }
  return [...counts.values()]
    .sort((a, b) => b.n - a.n || a.first - b.first)
    .slice(0, MAX_DOCS_PER_LINE)
    .map((e) => e.doc);
}

interface LineInfo { docs: DocumentRef[]; supported: string[]; kb: string[]; unsupported: string[] }

export type BlockKind = "paragraph" | "list" | "table" | "code" | "heading";

export interface Block { kind: BlockKind; start: number; end: number }

/** Split markdown into top-level blocks (1-based line ranges). */
export function splitBlocks(lines: string[]): Block[] {
  const blocks: Block[] = [];
  const isItem = (l: string) => /^\s*(?:[-*+]|\d+[.)])\s+/.test(l);
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    const start = i + 1;
    if (/^\s*```/.test(line)) {                                   // fenced code / diagram
      i++;
      while (i < lines.length && !/^\s*```/.test(lines[i])) i++;
      blocks.push({ kind: "code", start, end: Math.min(i + 1, lines.length) });
      i++;
      continue;
    }
    if (/^\s*#{1,6}\s/.test(line)) { blocks.push({ kind: "heading", start, end: start }); i++; continue; }
    if (/^\s*\|/.test(line)) {                                    // table
      while (i < lines.length && /^\s*\|/.test(lines[i])) i++;
      blocks.push({ kind: "table", start, end: i });
      continue;
    }
    if (isItem(line)) {                                            // list, incl. nested items
      let end = i;
      while (i < lines.length) {
        const l = lines[i];
        if (l.trim() && (isItem(l) || /^\s{2,}\S/.test(l))) { end = i; i++; continue; }
        if (!l.trim()) {                                          // a blank line inside a loose list
          let j = i + 1;
          while (j < lines.length && !lines[j].trim()) j++;
          if (j < lines.length && isItem(lines[j])) { i = j; continue; }
        }
        break;
      }
      blocks.push({ kind: "list", start, end: end + 1 });
      continue;
    }
    while (i < lines.length && lines[i].trim() && !isItem(lines[i]) && !/^\s*(```|\||#{1,6}\s)/.test(lines[i])) i++;
    blocks.push({ kind: "paragraph", start, end: i });
  }
  return blocks;
}

export interface ChipAnchor { start: number; kind: BlockKind; group: ChipGroup }

export interface ChipLayout {
  anchors: Map<number, ChipAnchor>;   // block end line -> chips for that block (or merged blocks)
  warnings: Map<number, string[]>;    // line -> "Not in sources" claims
}

/** Chips per block, grouped by source; warnings per line. */
export function buildChipLayout(
  answer: string,
  opts: { claims?: Claim[]; sources?: SourcesMap | null; complete: boolean },
): ChipLayout {
  const all = answer.split("\n");
  const lines = opts.complete ? all : all.slice(0, -1);       // the line being written is skipped
  const byLine = opts.claims ? claimsByLine(answer, opts.claims) : new Map<number, Claim[]>();
  const names = opts.sources ? Object.keys(opts.sources).sort((a, b) => b.length - a.length) : [];

  const info = new Map<number, LineInfo>();
  const warnings = new Map<number, string[]>();
  lines.forEach((raw, idx) => {
    const n = idx + 1;
    if (!raw.trim() || /^\s*```/.test(raw) || /^\s*\|?\s*:?-{3,}/.test(raw)) return;
    const checked = byLine.get(n);
    if (checked && checked.length) {
      const docs = new Map<string, DocumentRef>();
      const entry: LineInfo = { docs: [], supported: [], kb: [], unsupported: [] };
      for (const c of checked) {
        if (!c.supported) entry.unsupported.push(c.claim);
        else if (c.sources && c.sources.length) {
          c.sources.forEach((d) => docs.set(d.name, d));
          entry.supported.push(c.claim);
        } else entry.kb.push(c.claim);
      }
      entry.docs = [...docs.values()];
      if (entry.unsupported.length) warnings.set(n, entry.unsupported);
      info.set(n, entry);
    } else if (opts.sources) {
      const docs = docsForLine(raw, opts.sources, names);
      if (docs.length) info.set(n, { docs, supported: [plainLine(raw)], kb: [], unsupported: [] });
    }
  });

  // One group per block: every document used in it, most used first.
  const blockGroup = (b: Block): ChipGroup | null => {
    const counts = new Map<string, { doc: DocumentRef; n: number }>();
    const g: ChipGroup = { docs: [], supported: [], kb: [], unsupported: [], lineCount: 0 };
    for (let n = b.start; n <= b.end; n++) {
      const e = info.get(n);
      if (!e) continue;
      if (e.docs.length || e.kb.length) g.lineCount += 1;
      e.docs.forEach((d) => {
        const c = counts.get(d.name) ?? { doc: d, n: 0 };
        c.n += 1;
        counts.set(d.name, c);
      });
      g.supported.push(...e.supported);
      g.kb.push(...e.kb);
    }
    g.docs = [...counts.values()].sort((a, b2) => b2.n - a.n).map((c) => c.doc);
    return g.docs.length || g.kb.length ? g : null;
  };
  const keyOf = (g: ChipGroup | null) =>
    !g ? "" : g.docs.length ? g.docs.map((d) => d.name).sort().join("|") : "__kb";

  const anchors = new Map<number, ChipAnchor>();
  let pending: { key: string; block: Block; group: ChipGroup } | null = null;
  const flush = () => {
    if (pending) anchors.set(pending.block.end, { start: pending.block.start, kind: pending.block.kind, group: pending.group });
    pending = null;
  };
  for (const b of splitBlocks(lines)) {
    if (b.kind === "heading") { flush(); continue; }
    const g = blockGroup(b);
    const key = keyOf(g);
    if (!g) { flush(); continue; }
    const p = pending as { key: string; block: Block; group: ChipGroup } | null;
    if (p && p.key === key) {                                    // same documents: share one row
      p.group.supported.push(...g.supported);
      p.group.kb.push(...g.kb);
      p.group.lineCount += g.lineCount;
      p.block = b;
    } else {
      flush();
      pending = { key, block: b, group: g };
    }
  }
  flush();
  return { anchors, warnings };
}

/** Warnings on lines start..end. */
export function warningsInRange(layout: ChipLayout, start?: number, end?: number): string[] {
  if (!start || !end) return [];
  const out: string[] = [];
  for (let n = start; n <= end; n++) out.push(...(layout.warnings.get(n) ?? []));
  return out;
}
