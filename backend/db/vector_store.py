import os
import uuid
import hashlib
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue

# Global singleton client to avoid lock issues in local mode
_global_client = None

def get_qdrant_client():
    global _global_client
    if _global_client is None:
        qdrant_path = os.environ.get("QDRANT_PATH", "./qdrant_data")
        _global_client = QdrantClient(path=qdrant_path)
    return _global_client

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
