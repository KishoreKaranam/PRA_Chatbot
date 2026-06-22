const HINTS = [
  'What are business functions?',
  'List payment journey functions',
  'What rules govern payment capture?',
  'What activities does authentication have?',
  'Explain information objects',
  'Show me all domains',
];

export function EmptyState({ onHint }: { onHint: (h: string) => void }) {
  return (
    <div style={{
      textAlign: 'center', padding: '60px 24px',
      color: '#9ca3af', display: 'flex', flexDirection: 'column', alignItems: 'center',
    }}>
      <div style={{ fontSize: 52, marginBottom: 12 }}>💬</div>
      <p style={{ fontSize: 16, fontWeight: 600, color: '#374151', marginBottom: 6 }}>
        Ask anything about the Payment Reference Architecture
      </p>
      <p style={{ fontSize: 13, marginBottom: 24, color: '#6b7280' }}>
        Answers are grounded in SPARQL graph queries, full-text search, and semantic similarity.
      </p>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'center' }}>
        {HINTS.map(h => (
          <button
            key={h}
            onClick={() => onHint(h)}
            style={{
              background: '#fff', border: '1px solid #e5e7eb',
              borderRadius: 20, padding: '6px 14px',
              fontSize: 12, color: '#374151', cursor: 'pointer',
              transition: 'border-color 0.15s, box-shadow 0.15s',
            }}
            onMouseEnter={e => (e.currentTarget.style.borderColor = '#4f86f7')}
            onMouseLeave={e => (e.currentTarget.style.borderColor = '#e5e7eb')}
          >
            {h}
          </button>
        ))}
      </div>
    </div>
  );
}
