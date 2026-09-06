import { useState, useEffect, useRef, useCallback } from "react";
import { Send, Loader2, PanelLeftClose, PanelLeft, RotateCcw } from "lucide-react";
import { Sidebar } from "./components/Sidebar";
import { UserBubble, BotBubble } from "./components/ChatBubbles";
import { EmptyState } from "./components/EmptyState";
import { fetchHealth, fetchInstructions, sendQuestionStream, createSession } from "./api";
import type { HealthResponse, Instructions, ChatResponse } from "./api";
import "./App.css";

interface Message {
  role: "user" | "assistant";
  content?: string;
  response?: ChatResponse;
  timestamp: Date;
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [instructions, setInstructions] = useState<Instructions>({});
  const [sidebarOpen, setSidebarOpen] = useState(true);

  // Session ID — persisted in localStorage so page refreshes resume the same session
  const [sessionId, setSessionId] = useState<string | null>(() => {
    return localStorage.getItem("pra_session_id");
  });

  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const streamRef = useRef<ChatResponse | null>(null);

  useEffect(() => {
    fetchHealth().then(setHealth).catch(() => setHealth(null));
    fetchInstructions().then(setInstructions).catch(() => {});

    // Create a new session if none stored (first visit or cleared storage)
    if (!localStorage.getItem("pra_session_id")) {
      createSession()
        .then((id) => {
          localStorage.setItem("pra_session_id", id);
          setSessionId(id);
        })
        .catch((err) => {
          // Non-fatal: app still works in stateless mode if DB is unavailable
          console.warn("Could not create session:", err);
        });
    }
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const submit = useCallback(
    async (question: string) => {
      const q = question.trim();
      if (!q || loading) return;
      setInput("");
      setError("");

      setMessages((m) => [...m, { role: "user", content: q, timestamp: new Date() }]);
      setLoading(true);

      // Initialise streaming accumulator
      const streamResponse: ChatResponse = {
        question: q,
        rewritten_question: q,
        is_followup: false,
        intent: "exploratory",
        answer: "",
        retrieval_modes_used: [],
        evidence: [],
        confidence: null,
        warning: null,
        clarification_needed: null,
      };
      streamRef.current = streamResponse;

      // Placeholder assistant bubble
      setMessages((m) => [...m, { role: "assistant", response: { ...streamResponse }, timestamp: new Date() }]);

      const snapshot = () => {
        const s = { ...streamRef.current! };
        setMessages((m) => {
          const updated = m.slice();
          updated[updated.length - 1] = { ...updated[updated.length - 1], response: s };
          return updated;
        });
      };

      try {
        await sendQuestionStream(
          q,
          instructions,
          {
            // Stage 1 + 2 result
            onPipeline: (data) => {
              if (!streamRef.current) return;
              streamRef.current.rewritten_question = data.rewritten_question;
              streamRef.current.is_followup = data.is_followup;
              streamRef.current.intent = data.intent;
              snapshot();
            },
            // Stage 3 — clarification needed
            onClarification: (message) => {
              if (!streamRef.current) return;
              streamRef.current.answer = message;
              streamRef.current.clarification_needed = message;
              snapshot();
            },
            onRetrieval: (data) => {
              if (!streamRef.current) return;
              streamRef.current.retrieval_modes_used = data.retrieval_modes_used;
              streamRef.current.evidence = data.evidence as ChatResponse["evidence"];
              streamRef.current.warning = data.warning ?? null;
              snapshot();
            },
            onToken: (text) => {
              if (!streamRef.current) return;
              streamRef.current.answer += text;
              snapshot();
            },
            // Stage 7 — history now lives in DB; nothing to update client-side
            onDone: (data) => {
              if (!streamRef.current) return;
              streamRef.current.confidence = data.confidence;
              snapshot();
            },
            onError: (errMsg) => {
              setError(errMsg);
            },
          },
          sessionId,
        );
      } catch (e: unknown) {
        setError((e as Error).message ?? "An unexpected error occurred");
      }

      streamRef.current = null;
      setLoading(false);
      setTimeout(() => inputRef.current?.focus(), 50);
    },
    [loading, instructions, sessionId]
  );

  // New session — clear localStorage + messages + create fresh session
  const startNewSession = useCallback(async () => {
    localStorage.removeItem("pra_session_id");
    setMessages([]);
    setError("");
    try {
      const id = await createSession();
      localStorage.setItem("pra_session_id", id);
      setSessionId(id);
    } catch (err) {
      console.warn("Failed to create new session:", err);
      setSessionId(null);
    }
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit(input);
    }
  };

  const handleTextareaInput = (e: React.FormEvent<HTMLTextAreaElement>) => {
    const el = e.currentTarget;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 140) + "px";
  };

  const showQueries = instructions.show_sparql_queries ?? true;
  const showEvidence = instructions.show_raw_evidence ?? true;

  return (
    <div className="app-layout">
      <Sidebar
        instructions={instructions}
        onInstructionsChange={setInstructions}
        collapsed={!sidebarOpen}
      />
      <div className="main-panel">
        <header className="app-header">
          <button className="sidebar-toggle-btn" onClick={() => setSidebarOpen((o) => !o)} title={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}>
            {sidebarOpen ? <PanelLeftClose size={18} /> : <PanelLeft size={18} />}
          </button>
          <div className="app-header__logo">
            <svg viewBox="0 0 48 48" width="28" height="28">
              <defs><linearGradient id="hbg" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stopColor="#2563eb"/><stop offset="100%" stopColor="#7c3aed"/></linearGradient></defs>
              <circle cx="24" cy="24" r="22" fill="url(#hbg)"/>
              <circle cx="24" cy="14" r="3.5" fill="#93c5fd" opacity="0.9"/>
              <circle cx="14" cy="30" r="3" fill="#93c5fd" opacity="0.8"/>
              <circle cx="34" cy="30" r="3" fill="#93c5fd" opacity="0.8"/>
              <line x1="24" y1="17" x2="14" y2="27" stroke="#bfdbfe" strokeWidth="1.5" opacity="0.7"/>
              <line x1="24" y1="17" x2="34" y2="27" stroke="#bfdbfe" strokeWidth="1.5" opacity="0.7"/>
              <line x1="14" y1="30" x2="34" y2="30" stroke="#bfdbfe" strokeWidth="1" opacity="0.5"/>
            </svg>
          </div>
          <div>
            <div className="app-header__title">Payment Reference Architecture</div>
            <div className="app-header__subtitle">Knowledge Graph Assistant for Business Analysts</div>
          </div>
          <div className="app-header__actions">
            <button className="new-session-btn" onClick={startNewSession} title="Start a new conversation" disabled={loading}>
              <RotateCcw size={13} />
              New Chat
            </button>
            {health && (
              <span className={`status-pill ${health.graph_ready ? "status-pill--connected" : "status-pill--disconnected"}`}>
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: "currentColor", display: "inline-block" }} />
                {health.graph_ready ? `${health.graph_backend_label ?? "Neo4j"} Ready` : "Offline"}
              </span>
            )}
          </div>
        </header>
        <div className="messages-container">
          {messages.length === 0 && !loading ? (
            <EmptyState onHint={submit} />
          ) : (
            messages.map((m, i) =>
              m.role === "user" ? (
                <UserBubble key={i} text={m.content!} />
              ) : (
                loading && m.response?.answer === "" ? null : (
                  <BotBubble key={i} msg={m.response!} showQueries={showQueries} showEvidence={showEvidence} />
                )
              )
            )
          )}
          {loading && messages[messages.length - 1]?.response?.answer === "" && (
            <div className="loading-indicator">
              <div className="message-avatar message-avatar--bot">🤖</div>
              <div className="typing-dots"><span /><span /><span /></div>
              <span style={{ fontSize: 13, color: "var(--text-muted)" }}>Querying knowledge graph...</span>
            </div>
          )}
          {error && <div className="error-banner">{error}</div>}
          <div ref={bottomRef} />
        </div>
        <div className="input-container">
          <div className="input-wrapper">
            <textarea ref={inputRef} className="input-textarea" value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={handleKeyDown} onInput={handleTextareaInput} placeholder="Ask about payment domains, business functions, rules, activities..." rows={1} disabled={loading} />
            <button className="send-btn" onClick={() => submit(input)} disabled={loading || !input.trim()} title="Send message">
              {loading ? <Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /> : <Send size={18} />}
            </button>
          </div>
          <p className="input-hint">Press Enter to send &middot; Shift+Enter for new line</p>
        </div>
      </div>
    </div>
  );
}
