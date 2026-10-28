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
// 3. Grouped: consecutive lines backed by the same documents share ONE chip,
//    shown at the end of the group.

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

/** Chips per answer line (1-based), placed at the last line of each same-source group. */
export function buildChipGroups(
  answer: string,
  opts: { claims?: Claim[]; sources?: SourcesMap | null; complete: boolean },
): Map<number, ChipGroup> {
  const lines = answer.split("\n");
  const lastLine = opts.complete ? lines.length : lines.length - 1;   // the line being written is skipped
  const byLine = opts.claims ? claimsByLine(answer, opts.claims) : new Map<number, Claim[]>();
  const names = opts.sources ? Object.keys(opts.sources).sort((a, b) => b.length - a.length) : [];

  const info = new Map<number, LineInfo>();
  for (let n = 1; n <= lastLine; n++) {
    const raw = lines[n - 1];
    if (!raw.trim() || /^\s*```/.test(raw) || /^\s*\|?\s*:?-{3,}/.test(raw)) continue;
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
      info.set(n, entry);
    } else if (opts.sources) {
      const docs = docsForLine(raw, opts.sources, names);
      if (docs.length) info.set(n, { docs, supported: [plainLine(raw)], kb: [], unsupported: [] });
    }
  }

  const keyOf = (e?: LineInfo) =>
    !e ? "" : e.docs.length ? e.docs.map((d) => d.name).sort().join("|") : e.kb.length ? "__kb" : "";

  const out = new Map<number, ChipGroup>();
  const add = (line: number, part: Partial<ChipGroup>) => {
    const g = out.get(line) ?? { docs: [], supported: [], kb: [], unsupported: [], lineCount: 0 };
    if (part.docs) g.docs = part.docs;
    g.supported.push(...(part.supported ?? []));
    g.kb.push(...(part.kb ?? []));
    g.unsupported.push(...(part.unsupported ?? []));
    g.lineCount += part.lineCount ?? 0;
    out.set(line, g);
  };

  let run: { key: string; end: number; docs: DocumentRef[]; supported: string[]; kb: string[]; count: number } | null = null;
  const closeRun = () => {
    if (run) add(run.end, { docs: run.docs, supported: run.supported, kb: run.kb, lineCount: run.count });
    run = null;
  };
  for (let n = 1; n <= lastLine; n++) {
    if (!lines[n - 1].trim()) continue;                // blank lines do not break a group
    const e = info.get(n);
    const key = keyOf(e);
    if (e && e.unsupported.length) add(n, { unsupported: e.unsupported });
    if (!key) { closeRun(); continue; }
    if (run && (run as { key: string }).key === key) {
      const r = run as NonNullable<typeof run>;
      r.end = n; r.count += 1; r.supported.push(...e!.supported); r.kb.push(...e!.kb);
    } else {
      closeRun();
      run = { key, end: n, docs: e!.docs, supported: [...e!.supported], kb: [...e!.kb], count: 1 };
    }
  }
  closeRun();
  return out;
}

/** All chip groups on lines start..end, merged into one. */
export function groupsInRange(groups: Map<number, ChipGroup>, start?: number, end?: number): ChipGroup | null {
  if (!start || !end) return null;
  let merged: ChipGroup | null = null;
  for (let n = start; n <= end; n++) {
    const g = groups.get(n);
    if (!g) continue;
    if (!merged) merged = { docs: [...g.docs], supported: [...g.supported], kb: [...g.kb], unsupported: [...g.unsupported], lineCount: g.lineCount };
    else {
      const seen = new Set(merged.docs.map((d) => d.name));
      g.docs.forEach((d) => { if (!seen.has(d.name)) merged!.docs.push(d); });
      merged.supported.push(...g.supported); merged.kb.push(...g.kb);
      merged.unsupported.push(...g.unsupported); merged.lineCount += g.lineCount;
    }
  }
  return merged;
}
