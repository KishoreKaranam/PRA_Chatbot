# PRA Chatbot

A full-stack chatbot application for querying the **Payment Reference Architecture (PRA)** knowledge graph stored in GraphDB.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          User (Browser)                             │
│                     Streamlit UI (port 8501)                        │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ HTTP (REST/JSON)
┌───────────────────────────▼─────────────────────────────────────────┐
│                  FastAPI Backend (port 8000)                         │
│  ┌──────────────┐  ┌─────────────────────┐  ┌──────────────────┐   │
│  │  /api/chat   │  │ /api/config/        │  │  /api/health     │   │
│  │  endpoint    │  │ instructions (CRUD) │  │  endpoint        │   │
│  └──────┬───────┘  └─────────────────────┘  └──────────────────┘   │
│         │                                                            │
│  ┌──────▼──────────────────────────────────────────────────────┐    │
│  │              Retrieval Orchestrator                          │    │
│  │   Classifies question → chooses SPARQL / FTS / Similarity   │    │
│  └──────┬────────────┬────────────────────┬────────────────────┘    │
│         │            │                    │                          │
│  ┌──────▼──┐  ┌──────▼──────┐  ┌─────────▼──────────────────┐      │
│  │ SPARQL  │  │    FTS      │  │  Similarity (vector search)│      │
│  │ Service │  │  Service    │  │  NumPy + OpenAI Embeddings  │      │
│  └──────┬──┘  └──────┬──────┘  └─────────┬──────────────────┘      │
│         │            │                    │                          │
│  ┌──────▼────────────▼────────────────────▼──────────────────┐      │
│  │              GraphDB Client (httpx async)                  │      │
│  └───────────────────────────────────────────────────────────┘      │
│         │                                                            │
│  ┌──────▼──────────────────────┐                                    │
│  │  Answer Generation Service  │ ← OpenAI GPT-4o (or compatible)    │
│  └─────────────────────────────┘                                    │
└─────────────────────────────────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────────┐
│           GraphDB (localhost:7200)                                   │
│           Repository: Payment_Reference_Architecture                 │
│           Namespace:  https://example.org/pra#                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Technology Choices

| Component | Choice | Justification |
|-----------|--------|---------------|
| Backend | **FastAPI** | Async-native, OpenAPI docs, pydantic validation, production-ready |
| Frontend | **Streamlit** | Rapid prototyping of chat + config UI without React boilerplate |
| GraphDB client | **httpx (async)** | Standard SPARQL HTTP endpoint; no GraphDB SDK dependency |
| LLM | **OpenAI GPT-4o** | Best-in-class reasoning; swappable via env vars |
| Similarity search | **NumPy + OpenAI Embeddings** | No extra infrastructure; extensible adapter layer |
| Config persistence | **JSON file** | Simple, portable; swap for Redis/DB in production |

---

## Project Structure

```
PRA_Chatbot/
├── .env.example                  # Environment variable template
├── start_backend.bat             # Windows launcher for backend
├── start_frontend.bat            # Windows launcher for frontend
├── config/
│   └── agent_instructions.json  # Persisted agent settings
├── backend/
│   ├── requirements.txt
│   └── app/
│       ├── main.py               # FastAPI app entry point
│       ├── core/
│       │   ├── settings.py       # Pydantic settings (env vars)
│       │   └── log_config.py     # Structured logging
│       ├── models/
│       │   └── schemas.py        # Pydantic request/response models
│       ├── graphdb/
│       │   └── client.py         # SPARQL HTTP client + N-Triples parser
│       ├── services/
│       │   ├── sparql_service.py     # SPARQL CONSTRUCT retrieval
│       │   ├── fts_service.py        # Full-text search retrieval
│       │   ├── similarity_service.py # Vector/embedding search (adapter)
│       │   ├── orchestrator.py       # Hybrid retrieval coordination
│       │   ├── answer_service.py     # LLM answer generation
│       │   └── config_service.py     # Agent instructions CRUD
│       └── api/
│           ├── chat.py           # POST /api/chat
│           ├── config.py         # GET/PUT/POST /api/config/instructions
│           └── health.py         # GET /api/health
├── frontend/
│   ├── requirements.txt
│   └── app.py                   # Streamlit chat + config UI
└── docs/
    └── sample_queries/
        ├── 01_create_fts_connector.sparql
        ├── 02_construct_business_function.sparql
        ├── 03_fts_lucene_connector.sparql
        ├── 04_fts_builtin_magic.sparql
        ├── 05_ontology_schema.sparql
        └── 06_applicability_assessment.sparql
```

---

## Setup & Run

### Prerequisites

- Python 3.10+
- GraphDB running at `http://localhost:7200` with `Payment_Reference_Architecture` repository active
- OpenAI API key (for answer generation; set `OPENAI_API_KEY=sk-...`)

### 1. Configure environment

```powershell
cd C:\Users\Kishore.Karanam\Projects\PRA_Chatbot
Copy-Item .env.example backend\.env
# Edit backend\.env and set OPENAI_API_KEY, and any other values
```

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

Backend available at: http://localhost:8000  
API docs (Swagger): http://localhost:8000/docs

### 3. Start the frontend

Open a **second terminal**:

```powershell
.\start_frontend.bat
# or manually:
cd frontend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Frontend available at: http://localhost:8501

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GRAPHDB_BASE_URL` | `http://localhost:7200` | GraphDB server URL |
| `GRAPHDB_REPOSITORY` | `Payment_Reference_Architecture` | Repository name |
| `GRAPHDB_USERNAME` | _(empty)_ | Basic auth username |
| `GRAPHDB_PASSWORD` | _(empty)_ | Basic auth password |
| `OPENAI_API_KEY` | _(required)_ | OpenAI API key |
| `OPENAI_MODEL` | `gpt-4o` | LLM model name |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Compatible with Azure OpenAI / local Ollama |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model for similarity search |
| `EMBEDDING_ENABLED` | `false` | Set `true` to activate vector search |

---

## Retrieval Modes

### SPARQL CONSTRUCT
- Builds a dynamic SPARQL CONSTRUCT query based on detected PRA class keywords
- Returns an ontology sub-graph (triples) with class hierarchy, labels, descriptions, activities, and relationships
- Best for: **"What is…?", "How is X defined?", "What are the properties of…?"**

### Full-Text Search (FTS)
- Uses GraphDB's built-in Lucene index (enabled in repository config)
- Falls back to SPARQL REGEX if Lucene predicate is unavailable
- Best for: **"List all functions related to fraud", "Find activities for KYC"**

### Similarity Search (Vector)
- **Assumptions:** GraphDB 10.x does not natively support vector search
- Implemented as an **adapter layer** with NumPy + OpenAI embeddings
- All PRA entity texts are embedded once at startup and cached in-memory
- **To swap to Qdrant/Weaviate/Chroma:** replace `_NumPyBackend` in `similarity_service.py`
- Enable with `EMBEDDING_ENABLED=true` and a valid `OPENAI_API_KEY`
- Best for: **fuzzy/conceptual questions** like "something about monitoring payments"

### Hybrid (default)
- Auto-selects mode(s) based on question analysis:
  - Ontology-signal words → SPARQL first
  - Keyword-signal words → FTS first
  - No clear signal → Similarity
  - Falls back across modes if primary returns no results

---

## Agent Instructions (Configurable)

From the sidebar in the Streamlit UI (or via `PUT /api/config/instructions`):

| Setting | Options | Description |
|---------|---------|-------------|
| System Prompt | free text | LLM persona and constraints |
| Retrieval Strategy | hybrid / sparql / fts / similarity | Which mode to use |
| Answer Style | business / technical / concise / detailed | Tone of the answer |
| Strict Ontology Mode | on/off | Only answer from ontology definitions |
| Confidence Threshold | 0–1 | Minimum evidence quality to answer |
| Max Retrieved Results | 1–50 | Cap on results per mode |
| Show SPARQL Queries | on/off | Display query text in evidence panel |
| Show Raw Evidence | on/off | Show triples/hits in evidence panel |

Settings are persisted to `config/agent_instructions.json`.

---

## Sample Test Questions and Expected Behavior

| Question | Expected Mode | Expected Behavior |
|----------|---------------|-------------------|
| What are the main business functions in the PRA? | SPARQL | Returns all `pra:BusinessFunction` instances with labels and descriptions |
| What is a MainJourneyDomain? | SPARQL | Returns ontology class definition and instances |
| List all activities related to KYC or client monitoring | FTS + SPARQL | Finds activities via FTS on "KYC" then fetches their sub-graph |
| Which payment schemes have applicability assessments? | SPARQL | CONSTRUCT over `pra:ApplicabilityAssessment` and `pra:PaymentScheme` |
| What does the Channel Interface support? | SPARQL | Fetches `prai:channelInterface` and its relationships |
| Tell me about fraud and risk domains | FTS | Searches for "fraud" and "risk" across labels and descriptions |
| What is the purpose of the supporting domains? | SPARQL + FTS | Fetches `pra:SupportingDomain` instances and `pra:hasPurposeStatement` |
| Something about monitoring payments in real time | Similarity | Conceptual match via embedding cosine similarity |
| What business rules govern payment initiation? | SPARQL | CONSTRUCT for `pra:BusinessRule` linked to payment initiation functions |

---

## GraphDB FTS Connector Setup (Optional, Recommended)

For better FTS performance, create the Lucene connector by running the query in  
`docs/sample_queries/01_create_fts_connector.sparql`  
in the GraphDB SPARQL editor.

The built-in magic predicate (`http://www.ontotext.com/owlim/lucene#`) works without this connector  
(already enabled via `enable-fts-index = true` in the repository config).

---

## Similarity Search – Extending to a Vector Database

The `_NumPyBackend` class in `backend/app/services/similarity_service.py` is the plug-in point.  
To replace it with Qdrant:

```python
# 1. pip install qdrant-client
# 2. Implement QdrantBackend with same build() + search() interface
# 3. Swap in SimilarityRetrievalService._build_index():
#    self._backend = await QdrantBackend.build(records, ...)
```

No changes to the orchestrator, API, or frontend are needed.

---

## API Reference

### POST /api/chat

Request:
```json
{
  "question": "What are the main payment domains?",
  "agent_instructions": null
}
```

Response:
```json
{
  "question": "What are the main payment domains?",
  "answer": "The PRA defines the following main journey domains...",
  "retrieval_modes_used": ["sparql", "fts"],
  "evidence": [...],
  "confidence": 0.72,
  "warning": null
}
```

### GET /api/config/instructions
Returns current agent instructions.

### PUT /api/config/instructions
Updates agent instructions (body = `AgentInstructions` JSON).

### POST /api/config/instructions/reset
Resets to defaults.

### GET /api/health
Returns GraphDB connectivity status.
