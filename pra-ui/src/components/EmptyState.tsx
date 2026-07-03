const HINTS = [
  "What are business functions in Payment Processing?",
  "List all supporting domains",
  "What rules govern payment capture?",
  "Explain the payment routing engine",
  "What are preconditions for settlement?",
  "Show activities in reconciliation",
];

export function EmptyState({ onHint }: { onHint: (h: string) => void }) {
  return (
    <div className="empty-state">
      <div className="empty-state__icon">
        <svg viewBox="0 0 48 48" width="48" height="48">
          <defs><linearGradient id="ebg" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stopColor="#2563eb"/><stop offset="100%" stopColor="#7c3aed"/></linearGradient><linearGradient id="eacc" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stopColor="#60a5fa"/><stop offset="100%" stopColor="#a78bfa"/></linearGradient></defs>
          <circle cx="24" cy="24" r="22" fill="url(#ebg)" opacity="0.15"/>
          <circle cx="24" cy="14" r="4" fill="url(#eacc)" opacity="0.9"/>
          <circle cx="14" cy="30" r="3.5" fill="url(#eacc)" opacity="0.8"/>
          <circle cx="34" cy="30" r="3.5" fill="url(#eacc)" opacity="0.8"/>
          <circle cx="24" cy="36" r="2.5" fill="#93c5fd" opacity="0.7"/>
          <line x1="24" y1="18" x2="14" y2="27" stroke="#60a5fa" strokeWidth="1.5" opacity="0.6"/>
          <line x1="24" y1="18" x2="34" y2="27" stroke="#60a5fa" strokeWidth="1.5" opacity="0.6"/>
          <line x1="14" y1="33" x2="24" y2="36" stroke="#60a5fa" strokeWidth="1.2" opacity="0.5"/>
          <line x1="34" y1="33" x2="24" y2="36" stroke="#60a5fa" strokeWidth="1.2" opacity="0.5"/>
          <line x1="14" y1="30" x2="34" y2="30" stroke="#60a5fa" strokeWidth="1" opacity="0.4"/>
        </svg>
      </div>
      <h2 className="empty-state__title">Payment Reference Architecture</h2>
      <p className="empty-state__subtitle">
        Ask questions about payment domains, business functions, rules, and activities.
        Get instant answers grounded in the PRA knowledge graph &mdash; powered by SPARQL, full-text search, and AI.
      </p>
      <div className="empty-state__features">
        <div className="feature-card">
          <div className="feature-card__icon">🔗</div>
          <div className="feature-card__label">SPARQL Graph</div>
        </div>
        <div className="feature-card">
          <div className="feature-card__icon">🔍</div>
          <div className="feature-card__label">Full-Text Search</div>
        </div>
        <div className="feature-card">
          <div className="feature-card__icon">🧠</div>
          <div className="feature-card__label">Semantic Similarity</div>
        </div>
      </div>
      <div className="hint-chips">
        {HINTS.map((h) => (
          <button key={h} className="hint-chip" onClick={() => onHint(h)}>{h}</button>
        ))}
      </div>
    </div>
  );
}
