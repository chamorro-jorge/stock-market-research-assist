"""
Troceado de texto y generación de embeddings.

Modelo: databricks-gte-large-en (1024 dimensiones), un endpoint de Foundation
Model que ya viene servido en el workspace. La dimensión está fijada en el
esquema (VECTOR(1024)); cambiar de modelo obliga a migrar la columna y a
regenerar todos los vectores.
"""

import os
import re

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "databricks-gte-large-en")
EMBEDDING_DIM = 1024

# Un chunk de ~200 palabras entra de sobra en el límite del modelo y es
# suficientemente específico para que la similitud signifique algo.
CHUNK_WORDS = 200
CHUNK_OVERLAP = 40


def chunk_text(text: str, chunk_words: int = CHUNK_WORDS,
               overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    Parte un texto en fragmentos solapados.

    El solape evita que una idea que cae justo en la frontera quede partida en
    dos chunks y no se recupere bien en ninguno de los dos.
    """
    if not text:
        return []

    words = re.sub(r"\s+", " ", text).strip().split(" ")
    if len(words) <= chunk_words:
        return [" ".join(words)] if words != [""] else []

    step = chunk_words - overlap
    chunks = []
    for start in range(0, len(words), step):
        chunk = words[start:start + chunk_words]
        if len(chunk) < 20 and chunks:
            break  # una cola demasiado corta no aporta nada
        chunks.append(" ".join(chunk))
        if start + chunk_words >= len(words):
            break

    return chunks


def embed_texts(texts: list[str], batch_size: int = 16) -> list[list[float]]:
    """
    Convierte textos en vectores llamando al endpoint de Foundation Model.

    Se lanza por lotes porque el endpoint limita el tamaño de cada petición.
    """
    if not texts:
        return []

    from databricks.sdk import WorkspaceClient

    client = WorkspaceClient()
    vectors: list[list[float]] = []

    for start in range(0, len(texts), batch_size):
        batch = texts[start:start + batch_size]
        response = client.serving_endpoints.query(
            name=EMBEDDING_MODEL,
            input=batch,
        )
        for item in response.data:
            vectors.append(list(item.embedding))

    if len(vectors) != len(texts):
        raise RuntimeError(
            f"El endpoint devolvió {len(vectors)} vectores para {len(texts)} textos"
        )

    return vectors


def to_pgvector(vector: list[float]) -> str:
    """Formatea un vector como literal de pgvector: '[0.1,0.2,...]'."""
    return "[" + ",".join(f"{v:.6f}" for v in vector) + "]"
