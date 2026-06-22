import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import type { Evidence, SparqlEvidence, FtsEvidence, SimilarityEvidence } from '../api';
import { shortenUri } from '../api';

interface Props {
  evidence: Evidence[];
  showSparql: boolean;
}

export function EvidencePanel({ evidence, showSparql }: Props) {
  const [open, setOpen] = useState(false);

  if (!evidence || evidence.length === 0) return null;

  return (
    <div style={{ marginTop: 8 }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          display: 'flex', alignItems: 'center', gap: 6,
          background: '#f8f9fa', border: '1px solid #e5e7eb',
          borderRadius: 8, padding: '5px 12px', cursor: 'pointer',
          fontSize: 12, color: '#6b7280', fontWeight: 500,
        }}
      >
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        📋 Source Evidence
      </button>

      {open && (
        <div style={{
          marginTop: 8, border: '1px solid #e5e7eb', borderRadius: 10,
          overflow: 'hidden', background: '#fafafa',
        }}>
          {evidence.map((ev, i) => (
            <EvidenceBlock key={i} ev={ev} showSparql={showSparql} />
          ))}
        </div>
      )}
    </div>
  );
}

function EvidenceBlock({ ev, showSparql }: { ev: Evidence; showSparql: boolean }) {
  const mode = ev.mode;

  return (
    <div style={{ padding: '12px 16px', borderBottom: '1px solid #e5e7eb' }}>
      <div style={{
        fontSize: 11, fontWeight: 700, color: '#6b7280', textTransform: 'uppercase',
        letterSpacing: '0.05em', marginBottom: 8,
      }}>
        Mode: {mode}
      </div>

      {mode === 'sparql' && <SparqlBlock ev={ev as SparqlEvidence} showSparql={showSparql} />}
      {mode === 'fts' && <FtsBlock ev={ev as FtsEvidence} />}
      {mode === 'similarity' && <SimilarityBlock ev={ev as SimilarityEvidence} />}
    </div>
  );
}

function SparqlBlock({ ev, showSparql }: { ev: SparqlEvidence; showSparql: boolean }) {
  return (
    <>
      {showSparql && ev.query && (
        <pre style={{
          background: '#1e1e2e', color: '#cdd6f4', borderRadius: 6,
          padding: '8px 10px', fontSize: 11, overflowX: 'auto',
          marginBottom: 8, whiteSpace: 'pre-wrap', wordBreak: 'break-all',
        }}>
          {ev.query.trim()}
        </pre>
      )}
      <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 6 }}>
        {ev.triple_count} triples retrieved
      </div>
      {ev.triples.slice(0, 25).map((t, i) => (
        <div key={i} style={{ fontSize: 11, color: '#374151', padding: '2px 0', fontFamily: 'monospace' }}>
          <span style={{ color: '#6366f1' }}>{shortenUri(t.subject)}</span>
          {' → '}
          <span style={{ color: '#0891b2' }}>{shortenUri(t.predicate)}</span>
          {' → '}
          <span style={{ color: '#059669' }}>{shortenUri(t.obj)}</span>
        </div>
      ))}
      {ev.triples.length > 25 && (
        <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 4 }}>
          … and {ev.triples.length - 25} more triples
        </div>
      )}
    </>
  );
}

function FtsBlock({ ev }: { ev: FtsEvidence }) {
  return (
    <>
      <div style={{ fontSize: 12, marginBottom: 6 }}>
        <strong>Search term:</strong> <code style={{ background: '#f3f4f6', padding: '1px 5px', borderRadius: 3 }}>{ev.search_term}</code>
      </div>
      {ev.hits.map((h, i) => (
        <div key={i} style={{ marginBottom: 8 }}>
          <div style={{ fontWeight: 600, fontSize: 12 }}>{h.label} <span style={{ color: '#9ca3af', fontWeight: 400 }}>(score: {h.score.toFixed(3)})</span></div>
          <div style={{ fontSize: 11, color: '#6b7280', fontStyle: 'italic' }}>{h.snippet.slice(0, 200)}</div>
        </div>
      ))}
    </>
  );
}

function SimilarityBlock({ ev }: { ev: SimilarityEvidence }) {
  return (
    <>
      {ev.note && <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 6 }}>{ev.note}</div>}
      {ev.hits.map((h, i) => (
        <div key={i} style={{ marginBottom: 8 }}>
          <div style={{ fontWeight: 600, fontSize: 12 }}>{h.label} <span style={{ color: '#9ca3af', fontWeight: 400 }}>(similarity: {h.score.toFixed(3)})</span></div>
          <div style={{ fontSize: 11, color: '#6b7280', fontStyle: 'italic' }}>{h.text.slice(0, 200)}</div>
        </div>
      ))}
    </>
  );
}
