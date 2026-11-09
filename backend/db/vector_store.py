import os
import uuid
import hashlib
import logging
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue

_log = logging.getLogger(__name__)

# Global singleton client to avoid lock issues in local mode
_global_client = None

def get_qdrant_client():
    global _global_client
    if _global_client is None:
        qdrant_url = os.environ.get("QDRANT_URL")
        if qdrant_url:
            _log.info("Connecting to remote Qdrant server at %s", qdrant_url)
            _global_client = QdrantClient(url=qdrant_url)
        else:
            qdrant_path = os.environ.get("QDRANT_PATH", "./qdrant_data")
            _log.info("Initializing local embedded Qdrant client at %s", qdrant_path)
            _global_client = QdrantClient(path=qdrant_path)
    return _global_client

def reset_qdrant_client():
    """Reset the global singleton client (used in testing and lifecycle teardown)."""
    global _global_client
    if _global_client is not None:
        try:
            _global_client.close()
        except Exception:
            pass
        _global_client = None

class VectorStore:
    def __init__(self, collection_name: str = "needs"):
        self.collection_name = collection_name
        self.client = get_qdrant_client()
        
        if not self.client.collection_exists(collection_name=self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=384, distance=Distance.COSINE),
            )

    def upsert_need(self, need, vector):
        point_id = str(uuid.UUID(hashlib.md5(need.need_id.encode()).hexdigest()))
        
        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                PointStruct(
                    id=point_id,
                    vector=vector.tolist() if hasattr(vector, "tolist") else vector,
                    payload={
                        "need_id": need.need_id,
                        "need_type": need.need_type.value if hasattr(need.need_type, 'value') else need.need_type,
                        "location_text": need.location_text
                    }
                )
            ]
        )

    def search_similar(self, vector, need_type: str, limit: int = 5, score_threshold: float = 0.85):
        search_filter = Filter(
            must=[
                FieldCondition(
                    key="need_type",
                    match=MatchValue(value=need_type)
                )
            ]
        )
        
        res = self.client.query_points(
            collection_name=self.collection_name,
            query=vector.tolist() if hasattr(vector, "tolist") else vector,
            query_filter=search_filter,
            limit=limit,
            score_threshold=score_threshold
        )
        return res.points
