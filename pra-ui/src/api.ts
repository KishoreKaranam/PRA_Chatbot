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

export type Evidence = SparqlEvidence | FtsEvidence | SimilarityEvidence;

export interface ChatResponse {
  question: string;
  answer: string;
  retrieval_modes_used: string[];
  evidence: Evidence[];
  confidence: number | null;
  warning?: string | null;
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
  triple_count: number;
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
  onRetrieval: (data: { retrieval_modes_used: string[]; evidence: unknown[]; warning?: string | null }) => void;
  onToken: (text: string) => void;
  onDone: (data: { confidence: number | null }) => void;
  onError: (error: string) => void;
}

export async function sendQuestionStream(
  question: string,
  instructions: Instructions,
  callbacks: StreamCallbacks,
): Promise<void> {
  const r = await fetch(`${BASE}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, agent_instructions: instructions }),
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
    const { done, value } = await reader.read();
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
          case 'retrieval': callbacks.onRetrieval(data); break;
          case 'token':     callbacks.onToken(data.text); break;
          case 'done':      callbacks.onDone(data); break;
          case 'error':     callbacks.onError(data.detail); break;
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
