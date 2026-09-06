import { useState, useEffect, useRef, useCallback } from "react";
import { Settings, ChevronDown, ChevronUp, RotateCcw, Save, ExternalLink, CheckCircle, Clock } from "lucide-react";
import type { Instructions } from "../api";
import { saveInstructions, resetInstructions } from "../api";

interface Props {
  instructions: Instructions;
  onInstructionsChange: (i: Instructions) => void;
  collapsed: boolean;
}

const STRATEGIES = ["hybrid", "sparql", "fts", "similarity"] as const;
const STYLES = ["business", "technical", "concise", "detailed"] as const;
type SaveStatus = "idle" | "dirty" | "saving" | "saved" | "error";

export function Sidebar({ instructions, onInstructionsChange, collapsed }: Props) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [draft, setDraft] = useState<Instructions>(instructions);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle");
  const initialized = useRef(false);
  const autoSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!initialized.current && Object.keys(instructions).length > 0) {
      setDraft(instructions);
      initialized.current = true;
    }
  }, [instructions]);

  const persistSave = useCallback(async (data: Instructions) => {
    setSaveStatus("saving");
    try {
      const updated = await saveInstructions(data);
      onInstructionsChange(updated);
      setSaveStatus("saved");
      setTimeout(() => setSaveStatus("idle"), 2500);
    } catch {
      setSaveStatus("error");
      setTimeout(() => setSaveStatus("dirty"), 2000);
    }
  }, [onInstructionsChange]);

  const updateDraft = useCallback((patch: Partial<Instructions>) => {
    setDraft((prev) => {
      const next = { ...prev, ...patch };
      setSaveStatus("dirty");
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
      setSaveStatus("saved");
      setTimeout(() => setSaveStatus("idle"), 2000);
    } catch { /* ignore */ }
  };

  return (
    <aside className={`sidebar ${collapsed ? "sidebar--collapsed" : ""}`}>
      <div className="sidebar__brand">
        <div className="sidebar__brand-icon">
          <svg viewBox="0 0 48 48" width="32" height="32">
            <defs><linearGradient id="sbg" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stopColor="#60a5fa"/><stop offset="100%" stopColor="#a78bfa"/></linearGradient></defs>
            <circle cx="24" cy="14" r="4" fill="url(#sbg)" opacity="0.9"/>
            <circle cx="14" cy="30" r="3.5" fill="url(#sbg)" opacity="0.8"/>
            <circle cx="34" cy="30" r="3.5" fill="url(#sbg)" opacity="0.8"/>
            <circle cx="24" cy="36" r="2.5" fill="#93c5fd" opacity="0.7"/>
            <line x1="24" y1="18" x2="14" y2="27" stroke="#93c5fd" strokeWidth="1.5" opacity="0.6"/>
            <line x1="24" y1="18" x2="34" y2="27" stroke="#93c5fd" strokeWidth="1.5" opacity="0.6"/>
            <line x1="14" y1="33" x2="24" y2="36" stroke="#93c5fd" strokeWidth="1.2" opacity="0.5"/>
            <line x1="34" y1="33" x2="24" y2="36" stroke="#93c5fd" strokeWidth="1.2" opacity="0.5"/>
            <line x1="14" y1="30" x2="34" y2="30" stroke="#93c5fd" strokeWidth="1" opacity="0.4"/>
          </svg>
        </div>
        <div className="sidebar__brand-title">Payment Reference Architecture</div>
        <div className="sidebar__brand-subtitle">for Business Analysts</div>
      </div>

      <div className="sidebar__nav">
        <div className="sidebar__description">
          <p>Explore payment domains, business capabilities, rules, and activities using natural language.</p>
        </div>
      </div>

      <div className="settings-panel">
        <button className="settings-toggle" onClick={() => setSettingsOpen((o) => !o)}>
          <span style={{ display: "flex", alignItems: "center", gap: 8 }}><Settings size={15} /> Settings</span>
          {settingsOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>

        {settingsOpen && (
          <div className="settings-body">
            <div className={`save-status save-status--${saveStatus}`}>
              {saveStatus === "saved" && <><CheckCircle size={11} /> Saved</>}
              {saveStatus === "saving" && <><Clock size={11} /> Saving...</>}
              {saveStatus === "dirty" && <><Clock size={11} /> Unsaved changes</>}
              {saveStatus === "error" && <>Save failed</>}
              {saveStatus === "idle" && <>Auto-saves after 0.8s</>}
            </div>

            <span className="settings-label">System Prompt</span>
            <textarea className="settings-textarea settings-textarea--prompt" rows={8} value={draft.system_prompt ?? ""} onChange={(e) => updateDraft({ system_prompt: e.target.value })} placeholder="Enter system prompt for the AI assistant..." />

            <span className="settings-label">Retrieval Strategy</span>
            <select className="settings-select" value={draft.retrieval_strategy ?? "hybrid"} onChange={(e) => updateDraft({ retrieval_strategy: e.target.value })}>
              {STRATEGIES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>

            <span className="settings-label">Answer Style</span>
            <select className="settings-select" value={draft.answer_style ?? "business"} onChange={(e) => updateDraft({ answer_style: e.target.value })}>
              {STYLES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>

            <label className="settings-toggle-row">
              <span>Strict Ontology Mode</span>
              <input type="checkbox" className="toggle-switch" checked={draft.strict_ontology_mode ?? false} onChange={(e) => updateDraft({ strict_ontology_mode: e.target.checked })} />
            </label>

            <label className="settings-toggle-row">
              <span>Show Cypher Queries</span>
              <input type="checkbox" className="toggle-switch" checked={draft.show_sparql_queries ?? true} onChange={(e) => updateDraft({ show_sparql_queries: e.target.checked })} />
            </label>

            <label className="settings-toggle-row">
              <span>Show Evidence</span>
              <input type="checkbox" className="toggle-switch" checked={draft.show_raw_evidence ?? true} onChange={(e) => updateDraft({ show_raw_evidence: e.target.checked })} />
            </label>

            <span className="settings-label">Confidence Threshold: {(draft.confidence_threshold ?? 0.3).toFixed(2)}</span>
            <input type="range" className="settings-range" min={0} max={1} step={0.05} value={draft.confidence_threshold ?? 0.3} onChange={(e) => updateDraft({ confidence_threshold: Number(e.target.value) })} />

            <span className="settings-label">Max Entities: {draft.max_results ?? 10}</span>
            <input type="range" className="settings-range" min={1} max={100} step={1} value={draft.max_results ?? 10} onChange={(e) => updateDraft({ max_results: Number(e.target.value) })} />
            <span className="settings-hint">Entities fetched per retrieval mode</span>

            <span className="settings-label">Max Triples: {draft.max_triples ?? 500}</span>
            <input type="range" className="settings-range" min={50} max={5000} step={50} value={draft.max_triples ?? 500} onChange={(e) => updateDraft({ max_triples: Number(e.target.value) })} />
            <span className="settings-hint">CONSTRUCT query limit. Higher = richer context</span>

            <div className="settings-actions">
              <button className="settings-action-btn settings-action-btn--primary" onClick={handleManualSave} disabled={saveStatus === "saving"}>
                <Save size={13} /> Save
              </button>
              <button className="settings-action-btn settings-action-btn--secondary" onClick={handleReset}>
                <RotateCcw size={13} /> Reset
              </button>
            </div>
          </div>
        )}

        <div style={{ padding: "8px 16px", textAlign: "center" }}>
          <a href="http://localhost:8001/docs" target="_blank" rel="noreferrer" style={{ color: "var(--sidebar-muted)", fontSize: 11, textDecoration: "none", display: "inline-flex", alignItems: "center", gap: 4 }}>
            API Docs <ExternalLink size={10} />
          </a>
        </div>
      </div>
    </aside>
  );
}
