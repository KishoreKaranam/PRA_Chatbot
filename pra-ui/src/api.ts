// ── Types ─────────────────────────────────────────────────────────────────────

export interface Triple {
  subject: string;
  predicate: string;
  obj: string;
}

export interface SparqlEvidence {
  mode: 'sparql';
  query: string;
  triples: Triple[];
  triple_count: number;
}

export interface FtsHit {
  uri: string;
  label: string;
  score: number;
  snippet: string;
}

export interface FtsEvidence {
  mode: 'fts';
  search_term: string;
  hits: FtsHit[];
}

export interface SimilarityHit {
  uri: string;
  label: string;
  score: number;
  text: string;
}

export interface SimilarityEvidence {
  mode: 'similarity';
  hits: SimilarityHit[];
  note?: string;
}

export interface Neo4jNode {
  element_id: string;
  labels: string[];
  properties: Record<string, unknown>;
}

export interface Neo4jRelationship {
  element_id: string;
  type: string;
  start_node: string;
  end_node: string;
  properties: Record<string, unknown>;
}

export interface Neo4jGraphEvidence {
  mode: 'neo4j';
  query: string;
  results: Neo4jNode[];
  relationships: Neo4jRelationship[];
  result_count: number;
}

export type Evidence = SparqlEvidence | FtsEvidence | SimilarityEvidence | Neo4jGraphEvidence;

export interface ChatResponse {
  question: string;
  rewritten_question: string;
  is_followup: boolean;
  intent: string;
  answer: string;
  retrieval_modes_used: string[];
  evidence: Evidence[];
  confidence: number | null;
  warning?: string | null;
  clarification_needed?: string | null;
  session_id?: string | null;   // echoed back from backend
}

export interface ConversationTurn {
  role: 'user' | 'assistant';
  content: string;
}

export interface Instructions {
  system_prompt?: string;
  retrieval_strategy?: string;
  answer_style?: string;
  strict_ontology_mode?: boolean;
  confidence_threshold?: number;
  max_results?: number;
  max_triples?: number;
  show_sparql_queries?: boolean;
  show_raw_evidence?: boolean;
}

export interface HealthResponse {
  status: string;
  graph_ready: boolean;
  graph_backend: string;
  graph_backend_label: string;
  node_count: number;
  neo4j_uri?: string;
  error?: string;
}

// ── API calls ─────────────────────────────────────────────────────────────────

const BASE = '/api';

export async function fetchHealth(): Promise<HealthResponse> {
  const r = await fetch(`${BASE}/health`);
  if (!r.ok) throw new Error('Backend unreachable');
  return r.json();
}

export async function fetchInstructions(): Promise<Instructions> {
  const r = await fetch(`${BASE}/config/instructions`);
  if (!r.ok) throw new Error('Failed to fetch instructions');
  return r.json();
}

export async function saveInstructions(data: Instructions): Promise<Instructions> {
  const r = await fetch(`${BASE}/config/instructions`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!r.ok) throw new Error('Failed to save instructions');
  return r.json();
}

export async function resetInstructions(): Promise<Instructions> {
  const r = await fetch(`${BASE}/config/instructions/reset`, { method: 'POST' });
  if (!r.ok) throw new Error('Failed to reset instructions');
  return r.json();
}

export async function sendQuestion(question: string, instructions: Instructions): Promise<ChatResponse> {
  const r = await fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, agent_instructions: instructions }),
  });
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`Backend error ${r.status}: ${text.slice(0, 200)}`);
  }
  return r.json();
}

export interface StreamCallbacks {
  onPipeline: (data: { rewritten_question: string; is_followup: boolean; intent: string }) => void;
  onClarification: (message: string) => void;
  onRetrieval: (data: { retrieval_modes_used: string[]; evidence: unknown[]; warning?: string | null }) => void;
  onToken: (text: string) => void;
  onDone: (data: { confidence: number | null; session_id: string | null }) => void;
  onError: (error: string) => void;
}

// ── Session management ─────────────────────────────────────────────────────────

export interface CreateSessionResponse {
  session_id: string;
  message: string;
}

/**
 * Create a new conversation session on the backend.
 * Returns a session_id UUID string that should be stored in localStorage
 * and sent with every subsequent sendQuestionStream() call.
 */
export async function createSession(userId?: string): Promise<string> {
  const r = await fetch(`${BASE}/session`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId ?? null }),
  });
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`Failed to create session: ${r.status} ${text.slice(0, 200)}`);
  }
  const data: CreateSessionResponse = await r.json();
  return data.session_id;
}

// ── Chat history sidebar ─────────────────────────────────────────────────────

export interface SessionSummary {
  session_id: string;
  title: string;
  created_at: string | null;
  last_active: string | null;
  message_count: number;
}

export interface SessionListResponse {
  sessions: SessionSummary[];
}

export interface HistoryTurn {
  id: number;
  role: 'user' | 'assistant';
  raw_content: string;
  rewritten_content: string | null;
  intent: string | null;
  is_followup: boolean;
  entities: string[];
  confidence: number | null;
  modes_used: string[];
  timestamp: string | null;
}

export interface SessionHistoryResponse {
  session_id: string;
  turn_count: number;
  turns: HistoryTurn[];
}

/** List past conversations (most-recently-active first) for the sidebar. */
export async function listSessions(): Promise<SessionSummary[]> {
  const r = await fetch(`${BASE}/session`);
  if (!r.ok) throw new Error(`Failed to list sessions: ${r.status}`);
  const data: SessionListResponse = await r.json();
  return data.sessions;
}

/** Load the full turn-by-turn history for a session (used when re-opening a past chat). */
export async function loadSessionHistory(sessionId: string): Promise<HistoryTurn[]> {
  const r = await fetch(`${BASE}/session/${sessionId}/history`);
  if (!r.ok) throw new Error(`Failed to load history: ${r.status}`);
  const data: SessionHistoryResponse = await r.json();
  return data.turns;
}

/** Permanently delete a session and all its turns. */
export async function deleteSession(sessionId: string): Promise<void> {
  const r = await fetch(`${BASE}/session/${sessionId}`, { method: 'DELETE' });
  if (!r.ok) throw new Error(`Failed to delete session: ${r.status}`);
}

export async function sendQuestionStream(
  question: string,
  instructions: Instructions,
  callbacks: StreamCallbacks,
  sessionId: string | null = null,   // replaces conversationHistory
  signal?: AbortSignal,
): Promise<void> {
  const r = await fetch(`${BASE}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal,
    body: JSON.stringify({
      question,
      session_id: sessionId,
      agent_instructions: instructions,
    }),
  });

  if (!r.ok) {
    const text = await r.text();
    callbacks.onError(`Backend error ${r.status}: ${text.slice(0, 200)}`);
    return;
  }

  const reader = r.body?.getReader();
  if (!reader) { callbacks.onError('No response body'); return; }

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    let done: boolean, value: Uint8Array | undefined;
    try {
      ({ done, value } = await reader.read());
    } catch (e) {
      if ((e as Error).name === 'AbortError') return;
      throw e;
    }
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // SSE messages are separated by double newline
    let boundary: number;
    while ((boundary = buffer.indexOf('\n\n')) !== -1) {
      const rawMessage = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);

      let eventType = '';
      let dataStr = '';

      for (const line of rawMessage.split('\n')) {
        const trimmed = line.replace(/\r$/, ''); // handle \r\n
        if (trimmed.startsWith('event: ')) {
          eventType = trimmed.slice(7).trim();
        } else if (trimmed.startsWith('data: ')) {
          dataStr = trimmed.slice(6);
        }
      }

      if (!eventType || !dataStr) continue;

      try {
        const data = JSON.parse(dataStr);
        switch (eventType) {
          case 'pipeline':      callbacks.onPipeline(data); break;
          case 'clarification': callbacks.onClarification(data.message); break;
          case 'retrieval':     callbacks.onRetrieval(data); break;
          case 'token':         callbacks.onToken(data.text); break;
          case 'done':          callbacks.onDone(data); break;
          case 'error':         callbacks.onError(data.detail); break;
        }
      } catch {
        // skip malformed JSON
      }
    }
  }
}

export function shortenUri(uri: string, max = 55): string {
  if (uri.length <= max) return uri;
  if (uri.includes('#')) return '…#' + uri.split('#').pop();
  if (uri.includes('/')) return '…/' + uri.split('/').pop();
  return uri.slice(-max);
}
