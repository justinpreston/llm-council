# LLM Council - Copilot Instructions

A 3-stage deliberation system where multiple LLMs collaboratively answer questions through anonymized peer review.

## Architecture Overview

```
User Query → Stage 1 (parallel) → Stage 2 (anonymized ranking) → Stage 3 (chairman synthesis)
```

- **Backend**: FastAPI (Python 3.10+) on port 8001, uses OpenRouter API for multi-model access
- **Frontend**: React + Vite on port 5173, react-markdown for rendering
- **Storage**: JSON files in `data/conversations/`

### Key Files
- [backend/council.py](../backend/council.py) - Core 3-stage orchestration logic
- [backend/config.py](../backend/config.py) - Model configuration (`COUNCIL_MODELS`, `CHAIRMAN_MODEL`)
- [backend/openrouter.py](../backend/openrouter.py) - OpenRouter API client with parallel queries
- [frontend/src/components/Stage2.jsx](../frontend/src/components/Stage2.jsx) - De-anonymization display logic

## Critical Development Patterns

### Running the Backend
Always run from project root using module syntax:
```bash
uv run python -m backend.main  # Correct
cd backend && python main.py   # WRONG - breaks relative imports
```

### Backend Imports
Use relative imports in all backend modules:
```python
from .config import COUNCIL_MODELS    # Correct
from backend.config import ...        # Wrong
```

### Stage 2 Prompt Format
The ranking prompt requires strict formatting for reliable parsing. See `parse_ranking_from_text()` in [council.py](../backend/council.py):
```
FINAL RANKING:
1. Response C
2. Response A
3. Response B
```

### Frontend Markdown
Wrap all `<ReactMarkdown>` in `<div className="markdown-content">` for consistent 12px padding (defined in [index.css](../frontend/src/index.css)).

## Data Flow Nuances

- **Anonymization**: Stage 2 uses labels ("Response A, B, C...") to prevent bias. `label_to_model` mapping exists for de-anonymization.
- **Metadata Ephemeral**: `label_to_model` and `aggregate_rankings` are returned via API but NOT persisted to storage.
- **Graceful Degradation**: If some models fail, the system continues with successful responses.

## Port Configuration
| Service  | Port | Config Location |
|----------|------|-----------------|
| Backend  | 8001 | [backend/main.py](../backend/main.py) (uvicorn) |
| Frontend | 5173 | Vite default |
| CORS     | Both | [backend/main.py](../backend/main.py) middleware |

If changing ports, update both [backend/main.py](../backend/main.py) and [frontend/src/api.js](../frontend/src/api.js).

## Quick Commands
```bash
./start.sh              # Start both servers
uv sync                 # Install Python deps
cd frontend && npm i    # Install JS deps
```

## Testing
Use `test_openrouter.py` to verify API connectivity before adding new models to `COUNCIL_MODELS`.
