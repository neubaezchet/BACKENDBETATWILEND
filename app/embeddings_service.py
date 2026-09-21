"""
Servicio de Embeddings — Memoria vectorial de reglas y precedentes (RAG)
Vectoriza reglas de validación y precedentes de casos resueltos para que el
calificador IA (app/calificador_service.py) solo reciba en el prompt las
reglas/precedentes semánticamente relevantes al soporte que evalúa, en vez de
mandar todo el reglamento completo en cada llamada.

SDK: google-genai >= 2.4.0  (from google import genai)
Modelo: gemini-embedding-001, dimensión configurable (EMBEDDING_DIM en database.py).
"""

import os
import logging
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")


class EmbeddingsService:
    """Genera embeddings de texto con Gemini para RETRIEVAL_DOCUMENT (reglas,
    precedentes almacenados) y RETRIEVAL_QUERY (texto del soporte a evaluar)."""

    def __init__(self):
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY no configurada en variables de entorno")
        self.client = genai.Client(api_key=GEMINI_API_KEY)

    def _embed(self, textos, task_type: str, dim: int) -> dict:
        """
        Args:
            textos: str o lista de str a embeber (máx ~2000 tokens c/u)
            task_type: "RETRIEVAL_DOCUMENT" (reglas/precedentes) o "RETRIEVAL_QUERY" (consulta)
            dim: dimensión de salida del vector (debe coincidir con EMBEDDING_DIM de database.py)

        Returns:
            {"exito": bool, "vectores": list[list[float]], "error": str}
        """
        lista = [textos] if isinstance(textos, str) else list(textos)
        lista = [t.strip()[:8000] if t else "" for t in lista]

        if not lista or all(not t for t in lista):
            return {"exito": False, "vectores": [], "error": "Texto vacío — nada que embeber"}

        try:
            response = self.client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=lista,
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=dim,
                ),
            )
            vectores = [list(e.values) for e in response.embeddings]
            return {"exito": True, "vectores": vectores, "error": ""}
        except Exception as e:
            logger.error(f"❌ Error generando embeddings ({task_type}): {e}")
            return {"exito": False, "vectores": [], "error": str(e)}

    def embed_documentos(self, textos, dim: int) -> dict:
        """Para lo que se guarda en la BD: reglas y precedentes."""
        return self._embed(textos, task_type="RETRIEVAL_DOCUMENT", dim=dim)

    def embed_consulta(self, texto: str, dim: int) -> dict:
        """Para el texto del soporte que se está evaluando en el momento."""
        return self._embed(texto, task_type="RETRIEVAL_QUERY", dim=dim)


# ── Instancia global (fail-safe: si no hay API key, queda en None) ────────────
try:
    embeddings_service = EmbeddingsService()
    logger.info(f"✅ EmbeddingsService listo. Modelo: {EMBEDDING_MODEL}")
except Exception as e:
    logger.warning(f"⚠️ EmbeddingsService no disponible: {e}")
    embeddings_service = None
