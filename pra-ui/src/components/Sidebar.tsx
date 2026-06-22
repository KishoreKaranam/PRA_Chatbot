import { useState, useEffect, useRef, useCallback } from 'react';
import {
  Trash2, Settings, ChevronDown, ChevronUp,
  Activity, RotateCcw, Save, ExternalLink, CheckCircle, Clock
} from 'lucide-react';
import type { HealthResponse, Instructions } from '../api';
import { saveInstructions, resetInstructions } from '../api';

interface Props {
  health: HealthResponse | null;
  instructions: Instructions;
  onInstructionsChange: (i: Instructions) => void;
  onClearChat: () => void;
}

const STRATEGIES = ['hybrid', 'sparql', 'fts', 'similarity'] as const;
const STYLES = ['business', 'technical', 'concise', 'detailed'] as const;

type SaveStatus = 'idle' | 'dirty' | 'saving' | 'saved' | 'error';

export function Sidebar({ health, instructions, onInstructionsChange, onClearChat }: Props) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [draft, setDraft] = useState<Instructions>(instructions);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const initialized = useRef(false);
  const autoSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Sync draft once when instructions are first fetched from the backend
  useEffect(() => {
    if (!initialized.current && Object.keys(instructions).length > 0) {
      setDraft(instructions);
      initialized.current = true;
    }
  }, [instructions]);

  const persistSave = useCallback(async (data: Instructions) => {
    setSaveStatus('saving');
    try {
      const updated = await saveInstructions(data);
      onInstructionsChange(updated);
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 2500);
    } catch {
      setSaveStatus('error');
      setTimeout(() => setSaveStatus('dirty'), 2000);
    }
  }, [onInstructionsChange]);

  // Update draft + schedule auto-save 800ms after last change
  const updateDraft = useCallback((patch: Partial<Instructions>) => {
    setDraft(prev => {
      const next = { ...prev, ...patch };
      setSaveStatus('dirty');
      if (autoSaveTimer.current) clearTimeout(autoSaveTimer.current);
      autoSaveTimer.current = setTimeout(() => persistSave(next), 800);
      return next;
    });
  }, [persistSave]);

  const handleManualSave = () => {
    if (autoSaveTimer.current) clearTimeout(autoSaveTimer.current);
    persistSave(draft);
  };

  const handleReset = async () => {
    try {
      const reset = await resetInstructions();
      setDraft(reset);
      onInstructionsChange(reset);
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 2000);
    } catch { /* ignore */ }
  };

  const connected = health?.graphdb_connected ?? false;

  return (
    <aside style={{
      width: 280, minWidth: 280, background: 'var(--sidebar-bg)',
      borderRight: '1px solid var(--sidebar-border)',
      display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden',
    }}>
      {/* Brand */}
      <div style={{
        padding: '24px 20px 16px', textAlign: 'center',
        borderBottom: '1px solid var(--sidebar-border)',
      }}>
        <div style={{ fontSize: 36 }}>💳</div>
        <div style={{ color: 'var(--sidebar-text)', fontWeight: 700, fontSize: 15, marginTop: 6 }}>
          PRA Chatbot
        </div>
        <div style={{ color: 'var(--sidebar-muted)', fontSize: 11, marginTop: 2 }}>
          Payment Reference Architecture
        </div>
      </div>

      {/* Status pill */}
      <div style={{ padding: '12px 20px' }}>
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: 6,
          padding: '4px 12px', borderRadius: 20, fontSize: 12, fontWeight: 500,
          background: connected ? '#1e3a2f' : '#3b1f1f',
          color: connected ? 'var(--success)' : 'var(--danger)',
        }}>
          <Activity size={12} />
          {connected ? `GraphDB · ${health?.repository}` : 'Backend unreachable'}
        </span>
      </div>

      {/* Nav area grows */}
      <div style={{ flex: 1, padding: '8px 12px', overflowY: 'auto' }}>
        <button onClick={onClearChat} style={btnStyle}>
          <Trash2 size={15} />
          Clear Chat
        </button>
      </div>

      {/* Settings panel at bottom */}
      <div style={{ borderTop: '1px solid var(--sidebar-border)' }}>
        <button
          onClick={() => setSettingsOpen(o => !o)}
          style={{
            ...btnStyle, width: '100%', justifyContent: 'space-between',
            borderRadius: 0, padding: '12px 16px', background: 'transparent',
          }}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Settings size={15} />
            Settings & Instructions
          </span>
          {settingsOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>

        {settingsOpen && (
          <div style={{
            padding: '12px 16px 16px',
            background: '#1e2435',
            maxHeight: 480, overflowY: 'auto',
            display: 'flex', flexDirection: 'column', gap: 12,
          }}>
            {/* Auto-save status bar */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: 6,
              fontSize: 11, borderRadius: 6, padding: '5px 8px',
              background: saveStatus === 'saved'  ? '#1e3a2f' :
                          saveStatus === 'saving' ? '#1e2a3a' :
                          saveStatus === 'dirty'  ? '#2d2210' :
                          saveStatus === 'error'  ? '#3b1f1f' : '#252b3b',
              color:      saveStatus === 'saved'  ? 'var(--success)' :
                          saveStatus === 'saving' ? '#89b4fa' :
                          saveStatus === 'dirty'  ? '#facc15' :
                          saveStatus === 'error'  ? 'var(--danger)' : 'var(--sidebar-muted)',
            }}>
              {saveStatus === 'saved'  && <><CheckCircle size={11} /> Saved to backend</>}
              {saveStatus === 'saving' && <><Clock size={11} style={{ animation: 'spin 1s linear infinite' }} /> Saving…</>}
              {saveStatus === 'dirty'  && <><Clock size={11} /> Unsaved changes — saving soon…</>}
              {saveStatus === 'error'  && <>Save failed — click Save to retry</>}
              {saveStatus === 'idle'   && <>Changes auto-save after 0.8 s</>}
            </div>

            <FieldLabel>System Prompt</FieldLabel>
            <textarea
              rows={3}
              value={draft.system_prompt ?? ''}
              onChange={e => updateDraft({ system_prompt: e.target.value })}
              style={textareaStyle}
            />

            <FieldLabel>Retrieval Strategy</FieldLabel>
            <select
              value={draft.retrieval_strategy ?? 'hybrid'}
              onChange={e => updateDraft({ retrieval_strategy: e.target.value })}
              style={selectStyle}
            >
              {STRATEGIES.map(s => <option key={s} value={s}>{s}</option>)}
            </select>

            <FieldLabel>Answer Style</FieldLabel>
            <select
              value={draft.answer_style ?? 'business'}
              onChange={e => updateDraft({ answer_style: e.target.value })}
              style={selectStyle}
            >
              {STYLES.map(s => <option key={s} value={s}>{s}</option>)}
            </select>

            <label style={toggleRowStyle}>
              <span style={{ color: 'var(--sidebar-text)', fontSize: 12 }}>Strict Ontology Mode</span>
              <input type="checkbox"
                checked={draft.strict_ontology_mode ?? false}
                onChange={e => updateDraft({ strict_ontology_mode: e.target.checked })}
              />
            </label>

            <label style={toggleRowStyle}>
              <span style={{ color: 'var(--sidebar-text)', fontSize: 12 }}>Show SPARQL Queries</span>
              <input type="checkbox"
                checked={draft.show_sparql_queries ?? true}
                onChange={e => updateDraft({ show_sparql_queries: e.target.checked })}
              />
            </label>

            <label style={toggleRowStyle}>
              <span style={{ color: 'var(--sidebar-text)', fontSize: 12 }}>Show Source Evidence</span>
              <input type="checkbox"
                checked={draft.show_raw_evidence ?? true}
                onChange={e => updateDraft({ show_raw_evidence: e.target.checked })}
              />
            </label>

            <FieldLabel>Confidence Threshold: {draft.confidence_threshold?.toFixed(2) ?? '0.30'}</FieldLabel>
            <input type="range" min={0} max={1} step={0.05}
              value={draft.confidence_threshold ?? 0.3}
              onChange={e => updateDraft({ confidence_threshold: Number(e.target.value) })}
              style={{ width: '100%', accentColor: 'var(--accent)' }}
            />

            <FieldLabel>Max Entities per Mode: {draft.max_results ?? 10}</FieldLabel>
            <input type="range" min={1} max={100} step={1}
              value={draft.max_results ?? 10}
              onChange={e => updateDraft({ max_results: Number(e.target.value) })}
              style={{ width: '100%', accentColor: 'var(--accent)' }}
            />
            <span style={{ fontSize: 10, color: 'var(--sidebar-muted)' }}>
              Controls how many distinct entities are fetched per retrieval mode (SELECT LIMIT).
            </span>

            <FieldLabel>Max Triples (CONSTRUCT limit): {draft.max_triples ?? 500}</FieldLabel>
            <input type="range" min={50} max={5000} step={50}
              value={draft.max_triples ?? 500}
              onChange={e => updateDraft({ max_triples: Number(e.target.value) })}
              style={{ width: '100%', accentColor: 'var(--accent)' }}
            />
            <span style={{ fontSize: 10, color: 'var(--sidebar-muted)' }}>
              Controls the total number of triples returned by the SPARQL CONSTRUCT query. Higher = richer context, slower response.
            </span>

            <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
              <button
                onClick={handleManualSave}
                disabled={saveStatus === 'saving'}
                style={actionBtnStyle(saveStatus === 'saved' ? '#1e3a2f' : '#1a56db')}
              >
                {saveStatus === 'saving' ? '…' : saveStatus === 'saved' ? <><CheckCircle size={13} /> Saved</> : <><Save size={13} /> Save Now</>}
              </button>
              <button onClick={handleReset} style={actionBtnStyle('#374151')}>
                <RotateCcw size={13} /> Reset
              </button>
            </div>
          </div>
        )}

        {/* API docs link */}
        <div style={{ padding: '8px 16px', textAlign: 'center' }}>
          <a
            href="http://localhost:8001/docs"
            target="_blank"
            rel="noreferrer"
            style={{ color: 'var(--sidebar-muted)', fontSize: 11, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}
          >
            API Docs <ExternalLink size={10} />
          </a>
        </div>
      </div>
    </aside>
  );
}

// ── Mini helpers ──────────────────────────────────────────────────────────────

function FieldLabel({ children }: { children: React.ReactNode }) {
  return <span style={{ color: '#a6adc8', fontSize: 11, fontWeight: 500 }}>{children}</span>;
}

const btnStyle: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 8,
  width: '100%', padding: '9px 12px', borderRadius: 8,
  border: 'none', cursor: 'pointer',
  background: 'transparent', color: 'var(--sidebar-text)',
  fontSize: 13, fontWeight: 500,
  transition: 'background 0.15s',
};

const textareaStyle: React.CSSProperties = {
  width: '100%', background: '#252b3b', border: '1px solid var(--sidebar-border)',
  borderRadius: 6, color: 'var(--sidebar-text)', fontSize: 12,
  padding: '6px 8px', resize: 'vertical', fontFamily: 'inherit',
};

const selectStyle: React.CSSProperties = {
  width: '100%', background: '#252b3b', border: '1px solid var(--sidebar-border)',
  borderRadius: 6, color: 'var(--sidebar-text)', fontSize: 12,
  padding: '5px 8px',
};

const toggleRowStyle: React.CSSProperties = {
  display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer',
};

function actionBtnStyle(bg: string): React.CSSProperties {
  return {
    flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5,
    padding: '7px 0', borderRadius: 6, border: 'none', cursor: 'pointer',
    background: bg, color: '#fff', fontSize: 12, fontWeight: 600,
  };
}

// suppress unused warning
