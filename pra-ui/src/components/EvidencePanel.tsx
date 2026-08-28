import { useState } from "react";
import { ChevronDown, ChevronRight, Database, Search, Brain } from "lucide-react";
import type { Evidence, SparqlEvidence, FtsEvidence, SimilarityEvidence, Neo4jGraphEvidence } from "../api";
import { shortenUri } from "../api";

interface Props { evidence: Evidence[]; showQueries: boolean; }

export function EvidencePanel({ evidence, showQueries }: Props) {
  const [open, setOpen] = useState(false);

  if (!evidence || evidence.length === 0) return null;

  return (
    <div className="evidence-section">
      <button className={`evidence-toggle ${open ? "evidence-toggle--active" : ""}`} onClick={() => setOpen((o) => !o)}>
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        📋 Source Evidence ({evidence.length} {evidence.length === 1 ? "source" : "sources"})
      </button>
      {open && (
        <div className="evidence-body">
          {evidence.map((ev, i) => (
            <details key={i} className="evidence-source" open>
              <summary className="evidence-source__summary">
                {ev.mode === "sparql" && <><Database size={12} /> SPARQL / Neo4j</>}
                {ev.mode === "fts" && <><Search size={12} /> Full-text search</>}
                {ev.mode === "similarity" && <><Brain size={12} /> Semantic similarity</>}
              </summary>
              <div className="evidence-content">
                <EvidenceBlock ev={ev} showQueries={showQueries} />
              </div>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}

function EvidenceBlock({ ev, showQueries }: { ev: Evidence; showQueries: boolean }) {
  if (ev.mode === "neo4j") return <Neo4jBlock ev={ev as Neo4jGraphEvidence} showQueries={showQueries} />;
  if (ev.mode === "sparql") return <SparqlBlock ev={ev as SparqlEvidence} showQueries={showQueries} />;
  if (ev.mode === "fts") return <FtsBlock ev={ev as FtsEvidence} />;
  if (ev.mode === "similarity") return <SimilarityBlock ev={ev as SimilarityEvidence} />;
  return <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Unsupported evidence source.</div>;
}

function Neo4jBlock({ ev, showQueries }: { ev: Neo4jGraphEvidence; showQueries: boolean }) {
  return (
    <>
      {showQueries && ev.query && (
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 4, fontWeight: 600 }}>Cypher query</div>
      )}
      {showQueries && ev.query && (
        <pre style={{ background: "var(--surface-code)", color: "#e2e8f0", borderRadius: "var(--radius-sm)", padding: "10px 12px", fontSize: 11, overflowX: "auto", marginBottom: 10, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
          {ev.query.trim()}
        </pre>
      )}
      <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 8, fontWeight: 600 }}>
        {ev.result_count} graph results · {ev.relationships.length} relationships
      </div>
      {ev.results.slice(0, 30).map((node, i) => {
        const name = node.properties?.name ?? node.properties?.label ?? node.element_id;
        const description = node.properties?.description;
        return (
          <div key={node.element_id || i} className="fts-hit">
            <div className="fts-hit__title">
              {String(name)} <span className="fts-hit__score">({node.labels.join(", ")})</span>
            </div>
            {description != null && <div className="fts-hit__snippet">{String(description).slice(0, 250)}</div>}
          </div>
        );
      })}
      {ev.results.length > 30 && <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 6 }}>... and {ev.results.length - 30} more nodes</div>}
      {ev.relationships.length > 0 && (
        <div style={{ marginTop: 10, fontSize: 12 }}>
          <strong>Relationships</strong>
          {ev.relationships.slice(0, 30).map((relationship, i) => (
            <div key={relationship.element_id || i} className="triple-row">
              <span className="triple-row__s">{relationship.start_node}</span>
              <span className="triple-row__p">{relationship.type}</span>
              <span className="triple-row__o">{relationship.end_node}</span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function SparqlBlock({ ev, showQueries }: { ev: SparqlEvidence; showQueries: boolean }) {
  return (
    <>
      {showQueries && ev.query && (
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 4, fontWeight: 600 }}>SPARQL query</div>
      )}
      {showQueries && ev.query && (
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
