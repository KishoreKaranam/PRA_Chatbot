import { useState } from "react";
import { ChevronDown, ChevronRight, Database, Search, Brain } from "lucide-react";
import type { Evidence, SparqlEvidence, FtsEvidence, SimilarityEvidence } from "../api";
import { shortenUri } from "../api";

interface Props { evidence: Evidence[]; showSparql: boolean; }

export function EvidencePanel({ evidence, showSparql }: Props) {
  const [open, setOpen] = useState(false);
  const [activeTab, setActiveTab] = useState(0);

  if (!evidence || evidence.length === 0) return null;

  return (
    <div className="evidence-section">
      <button className={`evidence-toggle ${open ? "evidence-toggle--active" : ""}`} onClick={() => setOpen((o) => !o)}>
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        📋 Source Evidence ({evidence.length} {evidence.length === 1 ? "source" : "sources"})
      </button>
      {open && (
        <div className="evidence-body">
          <div className="evidence-tabs">
            {evidence.map((ev, i) => (
              <button key={i} className={`evidence-tab ${activeTab === i ? "evidence-tab--active" : ""}`} onClick={() => setActiveTab(i)}>
                {ev.mode === "sparql" && <><Database size={11} /> SPARQL</>}
                {ev.mode === "fts" && <><Search size={11} /> FTS</>}
                {ev.mode === "similarity" && <><Brain size={11} /> Similarity</>}
              </button>
            ))}
          </div>
          <div className="evidence-content">
            <EvidenceBlock ev={evidence[activeTab]} showSparql={showSparql} />
          </div>
        </div>
      )}
    </div>
  );
}

function EvidenceBlock({ ev, showSparql }: { ev: Evidence; showSparql: boolean }) {
  if (ev.mode === "sparql") return <SparqlBlock ev={ev as SparqlEvidence} showSparql={showSparql} />;
  if (ev.mode === "fts") return <FtsBlock ev={ev as FtsEvidence} />;
  return <SimilarityBlock ev={ev as SimilarityEvidence} />;
}

function SparqlBlock({ ev, showSparql }: { ev: SparqlEvidence; showSparql: boolean }) {
  return (
    <>
      {showSparql && ev.query && (
        <pre style={{ background: "var(--surface-code)", color: "#e2e8f0", borderRadius: "var(--radius-sm)", padding: "10px 12px", fontSize: 11, overflowX: "auto", marginBottom: 10, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
          {ev.query.trim()}
        </pre>
      )}
      <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 8, fontWeight: 600 }}>{ev.triple_count} triples retrieved</div>
      {ev.triples.slice(0, 30).map((t, i) => (
        <div key={i} className="triple-row">
          <span className="triple-row__s">{shortenUri(t.subject)}</span>
          <span className="triple-row__p">{shortenUri(t.predicate)}</span>
          <span className="triple-row__o">{shortenUri(t.obj)}</span>
        </div>
      ))}
      {ev.triples.length > 30 && <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 6 }}>... and {ev.triples.length - 30} more</div>}
    </>
  );
}

function FtsBlock({ ev }: { ev: FtsEvidence }) {
  return (
    <>
      <div style={{ fontSize: 12, marginBottom: 8 }}><strong>Search term:</strong> <code style={{ background: "var(--surface-sunken)", padding: "2px 6px", borderRadius: 4, fontSize: 11 }}>{ev.search_term}</code></div>
      {ev.hits.map((h, i) => (
        <div key={i} className="fts-hit">
          <div className="fts-hit__title">{h.label} <span className="fts-hit__score">(score: {h.score.toFixed(3)})</span></div>
          <div className="fts-hit__snippet">{h.snippet.slice(0, 250)}</div>
        </div>
      ))}
    </>
  );
}

function SimilarityBlock({ ev }: { ev: SimilarityEvidence }) {
  return (
    <>
      {ev.note && <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 8 }}>{ev.note}</div>}
      {ev.hits.map((h, i) => (
        <div key={i} className="fts-hit">
          <div className="fts-hit__title">{h.label} <span className="fts-hit__score">(sim: {h.score.toFixed(3)})</span></div>
          <div className="fts-hit__snippet">{h.text.slice(0, 250)}</div>
        </div>
      ))}
    </>
  );
}
