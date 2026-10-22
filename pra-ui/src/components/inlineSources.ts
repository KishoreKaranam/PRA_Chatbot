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
