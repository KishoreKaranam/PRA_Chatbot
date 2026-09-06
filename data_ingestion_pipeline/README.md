# File Ingest Backend

Backend that accepts file uploads from a front-end, validates them,
extracts data using a Claude LLM agent (via Azure AI Foundry) with tools, and stores the
resulting entities/relationships in a Neo4j graph database.

## Architecture

```
scripts/script1_api_server.py   Flask API: receives files, validates, stores, calls script2, responds
scripts/script2_llm_agent.py    Claude (Azure AI Foundry) agent loop: decides which tools to call
scripts/script3_tools.py        Tool schemas + implementations (read file, query/write Neo4j)
scripts/send_files.ps1          PowerShell client: sends files from a local folder to /upload
utils/file_parser.py            Per-format file parsing (xlsx, csv, docx, rtf, pdf, txt)
utils/validation.py             Extension/MIME validation and saving uploaded files
utils/logger.py                 Simple per-script file logger
config/settings.py              All configuration (paths, Foundry/Claude, Neo4j, API)
storage/uploads/                Saved uploaded files
logs/                            Single shared app.log for all scripts
```

## Flow

1. External system POSTs `/upload` with a list of files (base64 content) to script1.
2. Script1 validates format/MIME, saves accepted files, logs the outcome.
3. Script1 calls script2 (LLM agent) with the list of saved file paths and waits.
4. Script2 asks Claude (via Azure AI Foundry) which tool to use; Claude calls tools implemented
   in script3 (read_file, query_graph, write_graph) in a loop until done.
5. Script2 returns which files were processed to script1.
6. Script1 responds to the external caller with successes/failures and logs the result.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Then edit `.env` and fill in real values:

| Variable | Meaning |
|---|---|
| `AZURE_FOUNDRY_BASE_URL` | Your Foundry resource's Anthropic endpoint: `https://<resource-name>.services.ai.azure.com/anthropic` |
| `AZURE_FOUNDRY_API_KEY` | API key for that Foundry deployment |
| `ANTHROPIC_MODEL` | The **deployment name** you chose in Foundry (not necessarily the raw model id) |
| `ANTHROPIC_MAX_TOKENS` | Max tokens per Claude response |
| `MAX_AGENT_STEPS` | Safety limit on tool-call round trips per request |
| `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` | Neo4j connection |
| `API_HOST` / `API_PORT` | Where the Flask server listens (default `0.0.0.0:6666`) |

## Starting the server

Always start it using the venv's own interpreter (not a bare `python`, which may
resolve to a different, unrelated Python install without the project's dependencies):

```powershell
& .\.venv\Scripts\python.exe -m scripts.script1_api_server
```

This blocks and keeps running (`Press CTRL+C to quit`) — leave this terminal open.
It logs `* Running on http://127.0.0.1:<API_PORT>` once ready, using the port from `.env`.

If you see `OSError`/the server exits immediately, another process is probably already
bound to that port. Check with:

```powershell
Get-NetTCPConnection -LocalPort 6666 -State Listen
```

and either stop the conflicting process or change `API_PORT` in `.env` (requires
restarting the server for the change to take effect — `.env` is only read at startup).

## Calling it from outside

### Manually (any HTTP client)

```
POST http://127.0.0.1:6666/upload
Content-Type: application/json

{
  "files": [
    {
      "filename": "report.pdf",
      "mime_type": "application/pdf",
      "content": "<base64 encoded bytes>"
    }
  ]
}
```

Response shape:

```json
{
  "successful": ["report.pdf"],
  "failed": [
    {"filename": "badfile.exe", "reason": "unsupported format or mime type"}
  ]
}
```

### Using `scripts/send_files.ps1`

Sends every supported file in a local folder to `/upload` in a single request.

```powershell
# Uses the default URI http://127.0.0.1:6666/upload
.\scripts\send_files.ps1 -Folder "C:\path\to\your\files"

# Point at a different host/port (must match API_HOST/API_PORT in .env)
.\scripts\send_files.ps1 -Folder "C:\path\to\your\files" -Uri "http://127.0.0.1:6666/upload"

# Restrict to specific file types
.\scripts\send_files.ps1 -Folder "C:\path\to\your\files" -Filter "*.xlsx", "*.docx", "*.pdf"
```

Parameters:

| Parameter | Required | Default | Notes |
|---|---|---|---|
| `-Folder` | yes | — | Local folder to scan (non-recursive) for files to send |
| `-Filter` | no | `*.xlsx, *.xls, *.csv, *.doc, *.docx, *.txt, *.pdf, *.rtf` | Glob patterns to match under `-Folder` |
| `-Uri` | no | `http://127.0.0.1:6666/upload` | Must match the running server's `API_HOST`/`API_PORT` |

The script reads each matched file, base64-encodes its content, and POSTs them all as one
`files` array to `-Uri`, then prints the server's JSON response. If the server isn't running
or isn't reachable at `-Uri`, it prints the request failure via `Write-Error`.

