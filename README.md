# PRA Chatbot

A full-stack chatbot for querying the **Payments Reference Architecture (PRA)** knowledge graph stored in **Neo4j**.

The application combines Neo4j graph retrieval, full-text search, Azure-backed semantic similarity, LangGraph orchestration, Anthropic Claude answer generation, and PostgreSQL-backed conversation history.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        User (Browser)                               │
│              React / Vite UI  (port 5173)                           │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ HTTP REST + SSE streaming
┌───────────────────────────▼─────────────────────────────────────────┐
│                  FastAPI Backend  (port 8000)                        │
│  ┌─────────────────┐  ┌──────────────────────┐  ┌───────────────┐  │
│  │  /api/chat      │  │ /api/config/         │  │ /api/health   │  │
│  │  /api/chat/     │  │ instructions (CRUD)  │  │ /api/session  │  │
│  │  stream (SSE)   │  └──────────────────────┘  └───────────────┘  │
│  └──────┬──────────┘                                                 │
│         │                                                            │
│  ┌──────▼──────────────────────────────────────────────────────┐    │
│  │                  LangGraph Workflow (8 nodes)                │    │
│  │  load_history → resolve_context → classify_intent           │    │
│  │  → clarification_gate → retrieve → validate_evidence        │    │
│  │  → generate_answer → save_to_db                             │    │
│  └──────┬──────────────────────────────────────────────────────┘    │
│         │                                                            │
│  ┌──────▼──────────────────────────────────────────────────────┐    │
│  │               Retrieval Orchestrator (Hybrid)                │    │
│  │  ┌──────────────────┐ ┌────────────────┐ ┌───────────────┐  │    │
│  │  │  Graph Retrieval  │ │ FTS (CONTAINS) │ │    Vector     │  │    │
│  │  │  Neo4j Cypher     │ │  Neo4j         │ │  Azure+NumPy  │  │    │
│  │  └──────────────────┘ └────────────────┘ └───────────────┘  │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                               │                                      │
│  ┌────────────────────────────▼──────────────────────────────┐      │
│  │       Answer Generation  (Anthropic Claude Sonnet 4.6)     │      │
│  └───────────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────────┐
│  Neo4j       bolt://localhost:7687   database: neo4j  (789 nodes)    │
│  PostgreSQL  localhost:5432          database: pra_chatbot           │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Technology Stack

| Component | Choice | Notes |
|-----------|--------|-------|
| Backend | **FastAPI** | Async-native, SSE streaming, OpenAPI docs |
| Primary frontend | **React 19 + Vite** | Streaming chat UI |
| Legacy frontend | **Streamlit** | Still functional |
| Graph DB | **Neo4j** | Loaded from dump file |
| Graph client | **neo4j Python driver 6.2** | Bolt protocol, async |
| Workflow | **LangGraph** | 8-node stateful pipeline |
| LLM | **Anthropic Claude Sonnet 4.6** | Answer generation |
| Embeddings | **Azure OpenAI** `text-embedding-3-large` | Semantic similarity |
| Vector search | **NumPy in-memory** | Cosine similarity, 315 nodes embedded |
| Persistence | **PostgreSQL + SQLAlchemy async** | Conversation history, entity cache |
| Logging | **structlog** | Structured JSON logs |

---

## Project Structure

```
PRA_Chatbot/
├── .env.example
├── .gitignore
├── start_backend.bat                     # Windows launcher – FastAPI backend
├── start_frontend.bat                    # Windows launcher – Streamlit UI
├── start_frontend_react.bat              # Windows launcher – React/Vite UI
├── config/
│   └── agent_instructions.json
│
├── backend/
│   ├── requirements.txt
│   ├── .env                             # Active config (not committed)
│   ├── data/
│   │   └── pra_ontology.ttl            # Original PRA ontology (reference only)
│   └── app/
│       ├── main.py                      # FastAPI entry + lifespan hooks
│       ├── api/
│       │   ├── chat.py                  # POST /api/chat  GET /api/chat/stream
│       │   ├── config.py                # GET/PUT/POST /api/config/instructions
│       │   ├── health.py                # GET /api/health
│       │   └── session.py               # POST /api/session
│       ├── application/
│       │   ├── chat/pipeline_service.py
│       │   └── retrieval/orchestrator.py
│       ├── orchestration/langgraph/
│       │   ├── graph.py
│       │   ├── nodes.py
│       │   ├── edges.py
│       │   └── state.py
│       ├── infrastructure/
│       │   ├── knowledge_graph/
│       │   │   ├── base.py
│       │   │   └── neo4j/client.py      # Neo4jClient (Bolt, async)
│       │   ├── retrieval/
│       │   │   ├── neo4j/
│       │   │   │   ├── graph_service.py      # Cypher traversal queries
│       │   │   │   ├── full_text_service.py  # CONTAINS + Lucene fallback
│       │   │   │   └── vector_service.py     # Neo4j vector index (optional)
│       │   │   ├── sparql/service.py    # Cypher (named for compat)
│       │   │   ├── full_text/service.py # CONTAINS search
│       │   │   └── vector/service.py    # In-memory NumPy + Azure  ✅ ACTIVE
│       │   ├── llm/answer_service.py
│       │   ├── configuration/config_service.py
│       │   └── persistence/postgres/
│       ├── core/
│       │   ├── settings.py
│       │   ├── log_config.py
│       │   └── logging.py
│       ├── models/schemas.py
│       └── prompts/
│           ├── answer.py
│           ├── conversation.py
│           └── defaults.py
│
├── frontend/                            # Streamlit UI (legacy)
│   ├── requirements.txt
│   └── app.py
│
├── pra-ui/                              # React / Vite UI (primary)
│   ├── vite.config.ts                   # Proxy /api → :8000, SSE headers
│   ├── package.json
│   └── src/
│       ├── App.tsx
│       ├── api.ts
│       └── components/
│           ├── ChatBubbles.tsx
│           ├── EmptyState.tsx
│           ├── EvidencePanel.tsx
│           └── Sidebar.tsx
│
├── scripts/
│   └── neo4j/
│       ├── backfill_embeddings.py       # One-time: embed nodes into Neo4j
│       ├── compare_fts.py
│       ├── test_client.py
│       ├── test_graph_service.py
│       └── test_vector_service.py
│
└── docs/
    ├── generate_architecture.py
    └── sample_queries/                  # Legacy SPARQL queries (reference)
```

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.10+ | Backend |
| Node.js | 18+ | React frontend |
| Neo4j | 5.x | Graph database |
| PostgreSQL | 14+ | Conversation history |
| Anthropic API key or Azure AI API key | — | Required for the selected Claude provider |
| Azure OpenAI API key | — | `text-embedding-3-large` embeddings |

### Neo4j Setup — Load Dump File

```powershell
# Stop Neo4j first, then:
neo4j-admin database load `
  --from-path="C:\path\to\neo4j-2026-08-17T13-24-19.dump" `
  --database=neo4j `
  --overwrite-destination=true
# Start Neo4j, then verify:
```

```cypher
MATCH (n) RETURN count(n)     -- expected: 789
CALL db.labels()              -- Function, Domain, Rule, Phase, etc.
CALL db.relationshipTypes()   -- HAS_RULE, CONTAINS, APPLIES_TO, etc.
```

---

## Setup & Run

Before starting the application for the first time, ensure Neo4j and
PostgreSQL are running. Neo4j must contain the PRA data and both required
indexes must be created; the vector nodes must also have embeddings. Follow
[Required Neo4j Indexes](#required-neo4j-indexes) before starting the backend.

The backend creates its PostgreSQL tables automatically, but the PostgreSQL
server and the `pra_chatbot` database must already exist. Ensure that
`DATABASE_URL` in `backend/.env` matches the local PostgreSQL credentials.

### 1. Configure environment

```powershell
Copy-Item .env.example backend\.env
# Edit backend\.env with your credentials (see Environment Variables below)
```

The starter `.env.example` contains placeholders. For the current Neo4j
configuration, make sure `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`,
`NEO4J_DATABASE`, `RETRIEVAL_BACKEND=neo4j`, `FTS_BACKEND=neo4j`, and
`VECTOR_BACKEND=neo4j` are present in `backend/.env`. Also configure either
the direct Anthropic variables or the Azure AI Foundry variables described
below. Do not commit `backend/.env` or any real API keys.

### 2. Start the backend

```powershell
.\start_backend.bat
# or manually:
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

- Backend: http://localhost:8000
- Swagger: http://localhost:8000/docs

### 3. Start the React UI (primary)

```powershell
.\start_frontend_react.bat
# or manually:
cd pra-ui
npm install
npm run dev
```

- React UI: http://localhost:5173

### 4. Start the Streamlit UI (optional / legacy)

```powershell
.\start_frontend.bat
```

- Streamlit: http://localhost:8501

---

## Environment Variables (`backend/.env`)

### Neo4j (required)

| Variable | Example | Description |
|----------|---------|-------------|
| `NEO4J_URI` | `bolt://localhost:7687` | Bolt connection string |
| `NEO4J_USER` | `neo4j` | Username |
| `NEO4J_PASSWORD` | `password` | Password |
| `NEO4J_DATABASE` | `neo4j` | Database name |

### LLM Provider (one required)

| Variable | Example | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `anthropic` | `anthropic` \| `azure_anthropic` \| `openai` \| `azure` |
| `ANTHROPIC_API_KEY` | `sk-ant-...` | Anthropic API key |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Model name |
| `AZURE_AI_API_KEY` | `...` | Azure AI Foundry Claude API key when using `azure_anthropic` |
| `AZURE_AI_ENDPOINT` | `https://<resource>.services.ai.azure.com/api/projects/<project>` | Azure AI Foundry endpoint |
| `AZURE_AI_MODEL` | `claude-sonnet-5` | Azure Claude deployment name |
| `AZURE_AI_API_VERSION` | `2023-06-01` | Azure AI API version |

Set `LLM_PROVIDER=anthropic` to call Anthropic directly, or
`LLM_PROVIDER=azure_anthropic` to call Claude through Azure AI Foundry. Only
the credentials for the selected provider are required. `LLM_PROVIDER=azure`
is for Azure OpenAI and is separate from `azure_anthropic`.

### Embeddings — Azure OpenAI (required for vector search)

| Variable | Example | Description |
|----------|---------|-------------|
| `AZURE_OPENAI_API_KEY` | `7o7Nob...` | Azure API key |
| `AZURE_OPENAI_ENDPOINT` | `https://weave.cognitiveservices.azure.com/` | Endpoint |
| `AZURE_OPENAI_API_VERSION` | `2025-01-01-preview` | API version |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | `text-embedding-3-large` | Deployment name |
| `EMBEDDING_ENABLED` | `true` | Enable vector search |
| `EMBEDDING_MODEL` | `text-embedding-3-large` | Embedding model |

### Retrieval Backends

| Variable | Default | Description |
|----------|---------|-------------|
| `RETRIEVAL_BACKEND` | `neo4j` | Primary graph retrieval |
| `FTS_BACKEND` | `neo4j` | Full-text search |
| `VECTOR_BACKEND` | `legacy` | `legacy` = in-memory NumPy + Azure ✅ recommended; `neo4j` = requires `pra_embedding_index` in Neo4j |

### PostgreSQL

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:1234@localhost:5432/pra_chatbot` | SQLAlchemy async URL |
| `DB_POOL_SIZE` | `10` | Connection pool size |
| `DB_MAX_OVERFLOW` | `20` | Max overflow |

### Agent Defaults (overridable from UI sidebar)

| Variable | Default | Description |
|----------|---------|-------------|
| `DEFAULT_RETRIEVAL_STRATEGY` | `hybrid` | `hybrid` \| `sparql` \| `fts` \| `similarity` |
| `DEFAULT_ANSWER_STYLE` | `business` | `business` \| `technical` \| `concise` \| `detailed` |
| `DEFAULT_MAX_RESULTS` | `10` | Max results per retrieval mode |
| `DEFAULT_CONFIDENCE_THRESHOLD` | `0.3` | Minimum evidence score (0–1) |

---

## Neo4j Schema

### Node Labels & Properties

| Label | Properties |
|-------|-----------|
| `PRA` | `name`, `description` |
| `Phase` | `name`, `description` |
| `Domain` | `name`, `description`, `source` |
| `SupportingDomain` | `name`, `description`, `source` |
| `Function` | `name`, `description`, `applicable_schemes` |
| `PaymentScheme` | `name`, `description` |
| `Purpose` | `name`, `description` |
| `Rule` | `name`, `description` |
| `PreCondition` | `name`, `description` |
| `PostCondition` | `name`, `description` |
| `Input` | `name`, `description` |
| `Output` | `name`, `description` |
| `GuideDocument` | `name`, `description`, `source` |
| `Pattern` | `name`, `description`, `source` |
| `AntiPattern` | `name`, `description`, `source` |
| `Intent` | `name`, `description`, `source` |
| `WhyItMatters` | `name`, `description`, `source` |

### Relationships

```
PRA ──COMPRISES──────────────► Domain
PRA ──HAS_PHASE──────────────► Phase
Domain ──CONTAINS────────────► Function
Phase ──BELONGS_TO_PHASE─────► Function
Function ──HAS_PURPOSE───────► Purpose
Function ──HAS_RULE──────────► Rule
Function ──HAS_PRECONDITION──► PreCondition
Function ──HAS_POSTCONDITION─► PostCondition
Function ──HAS_INPUT─────────► Input
Function ──HAS_OUTPUT────────► Output
Function ──APPLIES_TO────────► PaymentScheme
Function ──PROVIDES_TO───────► Function
Function ──DEPENDS_ON_SUPPORTING──► SupportingDomain
SupportingDomain ──SUPPORTS_SCHEME──► PaymentScheme
PRA ──HAS_GUIDE───────────────► GuideDocument
PRA ──HAS_PATTERN─────────────► Pattern
GuideDocument ──DOCUMENTS─────► Pattern
Pattern ──HAS_ANTI_PATTERN────► AntiPattern
Pattern ──HAS_INTENT──────────► Intent
Pattern ──HAS_WHY_IT_MATTERS──► WhyItMatters
```

### Required Neo4j Indexes

After importing the PRA data, create the indexes below in Neo4j Browser (or
run them through a Neo4j Cypher client). The application is configured with
`FTS_BACKEND=neo4j` and `VECTOR_BACKEND=neo4j`, so both indexes are required
for the configured retrieval paths.

#### Full-text index

```cypher
CREATE FULLTEXT INDEX pra_fulltext IF NOT EXISTS
FOR (n:Function|Domain|SupportingDomain|Rule|PaymentScheme|Phase|Purpose|PreCondition|PostCondition|Input|Output|PRA|Pattern|AntiPattern|Intent|WhyItMatters|GuideDocument)
ON EACH [n.name, n.description, n.comment];
```

The full-text index is used by `db.index.fulltext.queryNodes()` for keyword
search. The application has a `CONTAINS` fallback, but creating this index is
recommended for complete and efficient FTS retrieval.

#### Vector index

```cypher
CREATE VECTOR INDEX pra_embedding_index IF NOT EXISTS
FOR (n:Function|Domain|SupportingDomain|Rule|PaymentScheme|Phase|Purpose|PreCondition|PostCondition|Input|Output|PRA|Pattern|AntiPattern|Intent|WhyItMatters|GuideDocument)
ON (n.embedding)
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 3072,
    `vector.similarity_function`: 'cosine'
  }
};
```

The vector index requires 3072-dimensional `embedding` properties on the PRA
nodes. Backfill those embeddings after creating the index:

```powershell
cd backend
.\venv\Scripts\python.exe ..\scripts\neo4j\backfill_embeddings.py --write
```

Verify that both indexes are online before starting the backend:

```cypher
SHOW INDEXES
YIELD name, type, state
WHERE name IN ['pra_fulltext', 'pra_embedding_index']
RETURN name, type, state;
```

Both indexes should have state `ONLINE`.

---

## Retrieval Modes

### Graph Retrieval (Neo4j Cypher)
Traverses the graph using Cypher. Resolves named PRA entities from the question and follows relationships.
Best for: **"What are the functions in Payment Initiation?"**, **"What rules govern X?"**

### Full-Text Search (Neo4j FTS)
Keyword matching on `name`, `description`, and `comment` using the Neo4j
Lucene full-text index `pra_fulltext`. If the index is unavailable, the
application falls back to a slower `CONTAINS` search.
Best for: **"List functions related to fraud"**, **"Find rules for KYC"**

### Vector Similarity — Neo4j native vector search (active)
The question is embedded with Azure OpenAI and searched against the Neo4j
`pra_embedding_index` using cosine similarity. The index must exist, be
`ONLINE`, and contain 3072-dimensional `embedding` properties.
Best for: **"Something about monitoring payments in real time"** (fuzzy / conceptual)

### Hybrid (default)
All 3 modes run in parallel. Results are merged and scored. Modes returning no results are skipped silently.

---

## API Reference

### POST /api/chat
```json
{ "question": "What is Payment Initiation?", "session_id": null, "agent_instructions": null }
```
Returns `ChatResponse` with `answer`, `retrieval_modes_used`, `evidence`, `confidence`.

### GET /api/chat/stream
SSE streaming endpoint (used by React UI).
Emits events in order: `pipeline` → `retrieval` → `token` (streamed) → `done`

### GET /api/health
```json
{
  "status": "ok",
  "graph_ready": true,
  "graph_backend": "neo4j",
  "graph_backend_label": "Neo4j",
  "neo4j_uri": "bolt://localhost:7687",
  "node_count": 789
}
```

### GET /api/config/instructions
Returns current agent instructions.

### PUT /api/config/instructions
Updates agent instructions.

### POST /api/config/instructions/reset
Resets to defaults.

### POST /api/session
Creates a new conversation session. Returns `{ session_id }`.

---

## Startup Behaviour

On every backend start:

1. **PostgreSQL tables created** — entity cache, conversation turns, retrieval logs
2. **Entity cache synced** — 652 nodes queried from Neo4j → `pra_entities_cache` for fast entity matching
3. **LangGraph compiled** — all 8 nodes and conditional edges validated
4. **Similarity index warmed** — 315 nodes embedded via Azure OpenAI in background (non-blocking)

---

## Enable Neo4j Native Vector Search

The required full-text and vector index creation statements, embedding
backfill command, and verification query are documented in
[Required Neo4j Indexes](#required-neo4j-indexes). Set the vector backend to
Neo4j in `backend/.env`:

```env
VECTOR_BACKEND=neo4j
```

---

## Sample Questions

| Question | Expected Mode |
|----------|--------------|
| What is Payment Initiation? | Graph + FTS |
| What are the functions in Payment Initiation? | Graph |
| What rules govern payment validation? | FTS + Graph |
| List all payment schemes | Graph |
| What are the preconditions for instruction submission? | Graph |
| Which functions provide to other functions? | Graph |
| Something about monitoring payments in real time | Similarity |
