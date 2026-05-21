# Asistente de Alejandro Rodríguez — API HTTP

Versión FastAPI del chatbot RAG (sustituye al Streamlit) para desplegar always-on
en un VPS.

## Endpoints

- `GET /health` → estado del servicio
- `POST /chat` → `{pregunta, thread_id?}` → `{respuesta, thread_id, ...}`
- `POST /chat/reset` → `{thread_id}` → devuelve un nuevo thread_id

## Ejecución local

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# editar .env y poner OPENAI_API_KEY
uvicorn api:app --reload
```

Abrir http://localhost:8000/docs para probar.

## Despliegue en VPS

Ver `deploy/INSTRUCCIONES_CLAUDE_CODE.md` para que Claude Code lo despliegue automáticamente.
