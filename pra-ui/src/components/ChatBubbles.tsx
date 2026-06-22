import type { ChatResponse } from '../api';
import { EvidencePanel } from './EvidencePanel';

interface UserBubbleProps { text: string; }
interface BotBubbleProps { msg: ChatResponse; showSparql: boolean; }

export function UserBubble({ text }: UserBubbleProps) {
  return (
    <div style={{ display: 'flex', justifyContent: 'flex-end', margin: '10px 0', animation: 'fadeUp 0.2s ease' }}>
      <div style={{
        background: 'linear-gradient(135deg, #4f86f7 0%, #1a56db 100%)',
        color: '#fff', padding: '12px 16px',
        borderRadius: '18px 18px 4px 18px',
        maxWidth: '72%', fontSize: 14, lineHeight: 1.55,
        boxShadow: '0 2px 6px rgba(79,134,247,0.3)',
        wordBreak: 'break-word',
      }}>
        {text}
      </div>
      <div style={avatarStyle('#4f86f7', '8px 0 0 8px')}>🧑</div>
    </div>
  );
}

export function BotBubble({ msg, showSparql }: BotBubbleProps) {
  const pct = Math.round((msg.confidence ?? 0) * 100);
  const confColor = pct >= 70 ? '#4ade80' : pct >= 40 ? '#facc15' : '#f87171';

  return (
    <div style={{ margin: '10px 0', animation: 'fadeUp 0.2s ease' }}>
      <div style={{ display: 'flex', justifyContent: 'flex-start' }}>
        <div style={avatarStyle('#1a1f2e', '0 8px 8px 0')}>🤖</div>
        <div style={{
          background: '#fff', color: '#1e1e2e',
          padding: '14px 18px', borderRadius: '18px 18px 18px 4px',
          maxWidth: '78%', fontSize: 14, lineHeight: 1.6,
          boxShadow: '0 2px 8px rgba(0,0,0,0.08)',
          border: '1px solid #e8eaf0', wordBreak: 'break-word',
        }}>
          {msg.warning && (
            <div style={{
              background: '#fff8e1', borderLeft: '3px solid #f59e0b',
              padding: '6px 10px', borderRadius: 4, fontSize: 12,
              color: '#92400e', marginBottom: 8,
            }}>
              ⚠️ {msg.warning}
            </div>
          )}

          {/* Render answer — split on newlines for readability */}
          {msg.answer.split('\n').map((line, i) => (
            <p key={i} style={{ margin: '3px 0' }}>{line}</p>
          ))}

          {/* Mode badges */}
          {msg.retrieval_modes_used?.length > 0 && (
            <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {msg.retrieval_modes_used.map(m => (
                <span key={m} style={{
                  background: '#eff6ff', border: '1px solid #bfdbfe',
                  borderRadius: 10, padding: '1px 9px', fontSize: 11, color: '#1d4ed8',
                }}>
                  🔍 {m}
                </span>
              ))}
            </div>
          )}

          {/* Confidence */}
          {msg.confidence != null && (
            <div style={{ marginTop: 6, fontSize: 11, color: '#6b7280' }}>
              <span style={{ color: confColor }}>■</span> Evidence confidence: <strong>{pct}%</strong>
            </div>
          )}
        </div>
      </div>

      {/* Evidence panel below the bubble */}
      <div style={{ paddingLeft: 48 }}>
        <EvidencePanel evidence={msg.evidence} showSparql={showSparql} />
      </div>
    </div>
  );
}

function avatarStyle(bg: string, margin: string): React.CSSProperties {
  return {
    width: 32, height: 32, borderRadius: '50%',
    background: bg, flexShrink: 0, display: 'flex',
    alignItems: 'center', justifyContent: 'center',
    fontSize: 15, margin: `4px ${margin}`,
  };
}
