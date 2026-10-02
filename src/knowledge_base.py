from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from langchain_ollama import OllamaEmbeddings

client = QdrantClient(url="http://localhost:6333")
embeddings = OllamaEmbeddings(model="nomic-embed-text")

def setup_collection():
    if not client.collection_exists(collection_name="incident_postmortems"):
        client.create_collection(
            collection_name="incident_postmortems",
            vectors_config=VectorParams(size=768, distance=Distance.COSINE),
        )
        sample_texts = [
            "API Server OOM killed due to memory leak. Fix: restart pod.",
            "Database connection pool exhausted. Fix: increased max connections."
        ]
        
        vectors = embeddings.embed_documents(sample_texts)
        points = []
        for i, (text, vector) in enumerate(zip(sample_texts, vectors)):
            points.append(PointStruct(id=i, vector=vector, payload={"text": text}))
            
        client.upsert(
            collection_name="incident_postmortems",
            points=points
        )

def search_postmortems(query: str, limit: int = 1) -> list[str]:
    setup_collection()
    query_vector = embeddings.embed_query(query)
    
    hits = client.search(  # type: ignore
        collection_name="incident_postmortems",
        query_vector=query_vector,
        limit=limit
    )
    
    return [hit.payload["text"] for hit in hits]
