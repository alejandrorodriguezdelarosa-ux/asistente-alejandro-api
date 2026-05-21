"""
Asistente Personal de Alejandro Rodríguez de la Rosa — API HTTP
================================================================

Versión FastAPI del chatbot RAG. Sustituye al Streamlit original para poder
desplegarse always-on en un VPS detrás de Nginx.

Endpoints:
    GET  /health           → comprueba que el servicio vive
    POST /chat             → recibe {pregunta, thread_id} y devuelve {respuesta}
    POST /chat/reset       → resetea la memoria de un thread

Variables de entorno requeridas:
    OPENAI_API_KEY         clave de OpenAI
    OPENAI_MODEL           (opcional) por defecto gpt-4o-mini
    CORS_ORIGINS           (opcional) lista separada por comas con los orígenes
                           permitidos (ej: "https://portafolio.óptimoia.es")
    SUPABASE_URL           (opcional) para logging de preguntas
    SUPABASE_KEY           (opcional) para logging de preguntas
"""

import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, TypedDict

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("asistente")


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
DOCS_DIR = os.getenv("DOCS_DIR", "docs")
CHROMA_DIR = os.getenv("CHROMA_DIR", "chroma_db")
RUTA_MD = os.path.join(DOCS_DIR, "alejandro_rag_completo.md")


# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Eres el asistente personal de Alejandro Rodríguez de la Rosa, integrado en su portafolio profesional.
Hablas en su nombre con reclutadores, headhunters y personas interesadas en su perfil profesional.

INSTRUCCIONES:
1. Basa SIEMPRE tus respuestas EXCLUSIVAMENTE en el contexto recuperado de la base de conocimiento. NO inventes datos sobre Alejandro. Si algo no está en el contexto, responde EXACTAMENTE con esta frase, sin añadir nada más: "Si deseas conocer esa información, ¡deberías hacerle una entrevista!"
2. Responde SIEMPRE en español, en tercera persona ("Alejandro ha trabajado…", "su experiencia es…"), nunca en primera persona como si fueras él.
3. Sé objetivo y honesto: no exageres ni adornes las respuestas. Si Alejandro reconoce un defecto o un fracaso, no lo escondas, contextualízalo.
4. Mantén un tono profesional pero cercano, como respondería un asistente bien entrenado de un candidato serio.
5. Estructura tus respuestas de forma clara pero breve: los reclutadores no quieren párrafos largos. Usa listas solo cuando aporten claridad.
6. Si te preguntan por el salario o expectativas económicas, responde EXACTAMENTE: "Si deseas conocer esa información, ¡deberías hacerle una entrevista!"
7. Si te preguntan algo personal incómodo, fuera de lugar o no relacionado con su perfil profesional o personal documentado, responde EXACTAMENTE: "Si deseas conocer esa información, ¡deberías hacerle una entrevista!"
8. Si el usuario pregunta cómo contactar con Alejandro, proporciónale el correo, teléfono o LinkedIn que aparezcan en la base de conocimiento.
9. Aprovecha la memoria de la conversación: si el usuario ya ha preguntado algo, conecta tus respuestas con el contexto previo.
10. Al final de respuestas largas o cuando sea natural hacerlo, sugiere de forma breve una pregunta de seguimiento útil para un reclutador (ejemplo: "¿Quieres que te cuente más sobre su experiencia en GEO?")."""


# ─────────────────────────────────────────────────────────────────────────────
# CHUNKING POR BLOQUES ID
# ─────────────────────────────────────────────────────────────────────────────

def cargar_bloques_rag(ruta_md: str):
    """Lee el .md y devuelve una lista de Documentos LangChain, uno por bloque ID."""
    from langchain_core.documents import Document

    with open(ruta_md, "r", encoding="utf-8") as f:
        texto = f.read()

    patron = re.compile(
        r"ID:\s*(?P<id>[\d\.]+)\s*\n"
        r"HECHO:\s*(?P<hecho>.+?)\s*\n"
        r"ENTIDADES:\s*(?P<entidades>.+?)\s*\n"
        r"PALABRAS_CLAVE:\s*(?P<keywords>.+?)\s*(?=\n---)",
        re.DOTALL,
    )

    documentos = []
    for m in patron.finditer(texto):
        bloque_id = m.group("id").strip()
        hecho = m.group("hecho").strip()
        entidades = m.group("entidades").strip()
        keywords = m.group("keywords").strip()
        contenido = f"{hecho}\n\nEntidades: {entidades}\nPalabras clave: {keywords}"

        documentos.append(Document(
            page_content=contenido,
            metadata={"id_bloque": bloque_id, "source": "alejandro_rag_completo.md"},
        ))

    return documentos


# ─────────────────────────────────────────────────────────────────────────────
# CARGA DEL AGENTE (una sola vez al arrancar)
# ─────────────────────────────────────────────────────────────────────────────

AGENTE = None
N_BLOQUES = 0


def construir_agente():
    """Construye el vectorstore, el LLM y el grafo LangGraph. Devuelve el agente compilado."""
    from langchain_community.vectorstores import Chroma
    from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.graph.message import add_messages

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("Falta la variable de entorno OPENAI_API_KEY.")

    if not os.path.exists(RUTA_MD):
        raise FileNotFoundError(f"No se encontró {RUTA_MD}.")

    documentos = cargar_bloques_rag(RUTA_MD)
    if not documentos:
        raise ValueError("No se pudo extraer ningún bloque del archivo Markdown.")

    embeddings = OpenAIEmbeddings(model="text-embedding-3-small", openai_api_key=api_key)
    vectorstore = Chroma.from_documents(
        documents=documentos,
        embedding=embeddings,
        collection_name="alejandro_perfil",
        persist_directory=CHROMA_DIR,
    )
    retriever = vectorstore.as_retriever(search_kwargs={"k": 5})

    llm = ChatOpenAI(model=OPENAI_MODEL, temperature=0.2, openai_api_key=api_key)

    class EstadoAsistente(TypedDict):
        mensajes: Annotated[list[BaseMessage], add_messages]
        contexto_rag: str

    def nodo_rag(estado):
        ultimo = None
        for msg in reversed(estado["mensajes"]):
            if isinstance(msg, HumanMessage):
                ultimo = msg.content
                break
        if not ultimo:
            return {"contexto_rag": ""}
        docs = retriever.invoke(ultimo)
        if not docs:
            return {"contexto_rag": "No se encontró información en la base de conocimiento."}
        fragmentos = [
            f"[Bloque {doc.metadata.get('id_bloque', '?')}]\n{doc.page_content}"
            for doc in docs
        ]
        return {"contexto_rag": "\n\n".join(fragmentos)}

    def nodo_generacion(estado):
        contexto = estado.get("contexto_rag", "")
        sys_prompt = SYSTEM_PROMPT
        if contexto:
            sys_prompt += (
                f"\n\nCONTEXTO DE LA BASE DE CONOCIMIENTO:\n{'=' * 50}\n"
                f"{contexto}\n{'=' * 50}\n"
                "Usa este contexto como ÚNICA fuente de información sobre Alejandro."
            )
        mensajes_completos = [SystemMessage(content=sys_prompt)] + estado["mensajes"]
        respuesta = llm.invoke(mensajes_completos)
        return {"mensajes": [respuesta]}

    grafo = StateGraph(EstadoAsistente)
    grafo.add_node("recuperar", nodo_rag)
    grafo.add_node("generar", nodo_generacion)
    grafo.add_edge(START, "recuperar")
    grafo.add_edge("recuperar", "generar")
    grafo.add_edge("generar", END)

    return grafo.compile(checkpointer=MemorySaver()), len(documentos)


# ─────────────────────────────────────────────────────────────────────────────
# SUPABASE (logging opcional)
# ─────────────────────────────────────────────────────────────────────────────

def guardar_pregunta(pregunta: str) -> None:
    """Loguea la pregunta en Supabase. Falla silenciosamente."""
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_KEY", "")
    if not url or not key:
        return
    endpoint = f"{url.rstrip('/')}/rest/v1/preguntas"
    if key.startswith(("sb_publishable_", "sb_secret_")):
        headers = {"apikey": key, "Content-Type": "application/json", "Prefer": "return=minimal"}
    else:
        headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        }
    try:
        requests.post(endpoint, json={"pregunta": pregunta}, headers=headers, timeout=3)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# FASTAPI
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global AGENTE, N_BLOQUES
    log.info("Construyendo agente RAG…")
    AGENTE, N_BLOQUES = construir_agente()
    log.info("Agente listo (%d bloques indexados).", N_BLOQUES)
    yield


app = FastAPI(
    title="Asistente de Alejandro Rodríguez",
    description="API HTTP del chatbot RAG personal.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    pregunta: str = Field(..., min_length=1, max_length=2000)
    thread_id: str | None = None


class ChatResponse(BaseModel):
    respuesta: str
    thread_id: str
    tiempo_ms: int
    n_bloques: int
    modelo: str


class ResetRequest(BaseModel):
    thread_id: str


@app.get("/health")
def health():
    return {
        "status": "ok",
        "modelo": OPENAI_MODEL,
        "bloques_indexados": N_BLOQUES,
        "agente_listo": AGENTE is not None,
    }


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    if AGENTE is None:
        raise HTTPException(status_code=503, detail="Agente no inicializado.")

    from langchain_core.messages import HumanMessage as HMsg

    thread_id = req.thread_id or f"web-{uuid.uuid4().hex[:8]}"
    guardar_pregunta(req.pregunta)

    inicio = datetime.now()
    try:
        config = {"configurable": {"thread_id": thread_id}}
        entrada = {"mensajes": [HMsg(content=req.pregunta)]}
        resultado = AGENTE.invoke(entrada, config=config)
        tiempo_ms = int((datetime.now() - inicio).total_seconds() * 1000)
        respuesta = resultado["mensajes"][-1].content
    except Exception as e:
        log.exception("Error al generar respuesta")
        raise HTTPException(status_code=500, detail=f"Error al generar respuesta: {e}")

    return ChatResponse(
        respuesta=respuesta,
        thread_id=thread_id,
        tiempo_ms=tiempo_ms,
        n_bloques=N_BLOQUES,
        modelo=OPENAI_MODEL,
    )


@app.post("/chat/reset")
def reset(req: ResetRequest):
    """Devuelve un nuevo thread_id. La memoria del antiguo queda huérfana y será
    recolectada por MemorySaver. No hay borrado activo porque MemorySaver in-memory
    no expone API de borrado, pero como cada thread es independiente basta con
    cambiar de id."""
    return {"thread_id": f"web-{uuid.uuid4().hex[:8]}"}
