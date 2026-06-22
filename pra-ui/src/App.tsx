import { useState, useEffect, useRef, useCallback } from "react";
import { Send, Loader2 } from "lucide-react";
import { Sidebar } from "./components/Sidebar";
import { UserBubble, BotBubble } from "./components/ChatBubbles";
import { EmptyState } from "./components/EmptyState";
import { fetchHealth, fetchInstructions, sendQuestion } from "./api";
import type { HealthResponse, Instructions, ChatResponse } from "./api";

interface Message {
  role: "user" | "assistant";
  content?: string;
  response?: ChatResponse;
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [instructions, setInstructions] = useState<Instructions>({});
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    fetchHealth().then(setHealth).catch(() => setHealth(null));
    fetchInstructions().then(setInstructions).catch(() => {});
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const submit = useCallback(async (question: string) => {
    const q = question.trim();
    if (!q || loading) return;
    setInput("");
    setError("");
    setMessages((m) => [...m, { role: "user", content: q }]);
    setLoading(true);
    try {
      const res = await sendQuestion(q, instructions);
      setMessages((m) => [...m, { role: "assistant", response: res }]);
    } catch (e: unknown) {
      setError((e as Error).message ?? "Unexpected error");
    }
    setLoading(false);
    setTimeout(() => inputRef.current?.focus(), 50);
  }, [loading, instructions]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit(input);
    }
  };

  const showSparql = instructions.show_sparql_queries ?? true;

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden" }}>
      <Sidebar
        health={health}
        instructions={instructions}
        onInstructionsChange={setInstructions}
        onClearChat={() => setMessages([])}
      />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {/* Header */}
        <div style={{
          background: "linear-gradient(135deg,#1a1f2e 0%,#2d3a5e 100%)",
          padding: "16px 28px", display: "flex", alignItems: "center", gap: 14,
          boxShadow: "0 2px 8px rgba(0,0,0,0.12)", flexShrink: 0,
        }}>
          <span style={{ fontSize: 28 }}>💳</span>
          <div>
            <div style={{ color: "#fff", fontWeight: 700, fontSize: 17, lineHeight: 1.2 }}>
              Payment Reference Architecture Chatbot
            </div>
            <div style={{ color: "#89b4fa", fontSize: 11, marginTop: 2 }}>
              Ask about business functions, rules, activities, domains, schemes — grounded in the PRA knowledge graph.
            </div>
          </div>
        </div>

        {/* Messages */}
        <div style={{ flex: 1, overflowY: "auto", padding: "16px 24px 8px" }}>
          {messages.length === 0 && !loading ? (
            <EmptyState onHint={submit} />
          ) : (
            messages.map((m, i) =>
              m.role === "user"
                ? <UserBubble key={i} text={m.content!} />
                : <BotBubble key={i} msg={m.response!} showSparql={showSparql} />
            )
          )}

          {loading && (
            <div style={{ display: "flex", alignItems: "center", gap: 8, color: "#6b7280", padding: "8px 0", animation: "fadeUp 0.2s ease" }}>
              <div style={{ width: 32, height: 32, borderRadius: "50%", background: "#1a1f2e", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 15 }}>
                🤖
              </div>
              <Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} />
              <span style={{ fontSize: 13 }}>Searching the knowledge graph...</span>
            </div>
          )}

          {error && (
            <div style={{
              background: "#fef2f2", border: "1px solid #fecaca",
              borderRadius: 10, padding: "12px 16px", color: "#dc2626", fontSize: 13, marginTop: 8,
            }}>
              {error}
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Input bar */}
        <div style={{ padding: "12px 24px 16px", background: "#fff", borderTop: "1px solid #e5e7eb", flexShrink: 0 }}>
          <div
            style={{
              display: "flex", gap: 10, alignItems: "flex-end",
              background: "#f9fafb", border: "1.5px solid #e5e7eb",
              borderRadius: 14, padding: "10px 14px",
            }}
            onFocusCapture={e => {
              const el = e.currentTarget as HTMLDivElement;
              el.style.borderColor = "#4f86f7";
              el.style.boxShadow = "0 0 0 3px rgba(79,134,247,0.15)";
            }}
            onBlurCapture={e => {
              const el = e.currentTarget as HTMLDivElement;
              el.style.borderColor = "#e5e7eb";
              el.style.boxShadow = "none";
            }}
          >
            <textarea
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about payment domains, business functions, rules, schemes..."
              rows={1}
              disabled={loading}
              style={{
                flex: 1, border: "none", outline: "none", resize: "none",
                background: "transparent", fontSize: 14, lineHeight: 1.5,
                color: "#1e1e2e", fontFamily: "inherit",
                maxHeight: 120, overflowY: "auto",
              }}
              onInput={e => {
                const el = e.currentTarget;
                el.style.height = "auto";
                el.style.height = Math.min(el.scrollHeight, 120) + "px";
              }}
            />
            <button
              onClick={() => submit(input)}
              disabled={loading || !input.trim()}
              style={{
                background: input.trim() && !loading ? "linear-gradient(135deg,#4f86f7,#1a56db)" : "#e5e7eb",
                border: "none", borderRadius: 10, padding: "8px 10px",
                cursor: input.trim() && !loading ? "pointer" : "not-allowed",
                display: "flex", alignItems: "center", justifyContent: "center",
              }}
            >
              <Send size={18} color={input.trim() && !loading ? "#fff" : "#9ca3af"} />
            </button>
          </div>
          <p style={{ fontSize: 11, color: "#9ca3af", textAlign: "center", marginTop: 6 }}>
            Press Enter to send &middot; Shift+Enter for new line
          </p>
        </div>
      </div>
    </div>
  );
}
