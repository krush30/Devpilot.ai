# DevPilot AI

Autonomous AI software engineering platform (multi-agent, RAG, MCP).

## Quick start (Week 1)
```bash
cp .env.example .env          # add GROQ_API_KEY (and optionally OPENROUTER_API_KEY)
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest                         # router fallback tests
uvicorn app.main:app --reload  # http://localhost:8000/docs
```
Test: `POST /api/chat {"message": "Explain FastAPI dependency injection"}`
Check providers: `GET /api/llm/health`

Frontend (from repo root): `npx create-next-app@latest frontend --ts --tailwind --app`
