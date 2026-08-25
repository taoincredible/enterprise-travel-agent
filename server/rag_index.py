import json
from pathlib import Path

from pymilvus import MilvusClient
from sentence_transformers import SentenceTransformer


ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "data" / "documents"
MODEL = ROOT / "data" / "models" / "bge-small-zh-v1.5"
DB = ROOT / "data" / "rag_knowledge" / "milvus_lite.db"
COLLECTION = "business_travel_knowledge"


def split_text(text: str, max_chars: int = 600) -> list[str]:
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    chunks = []
    current = ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 2 > max_chars:
            chunks.append(current)
            current = ""
        current = f"{current}\n\n{paragraph}".strip()
    if current:
        chunks.append(current)
    return chunks


def build_index() -> None:
    print("加载本地 Embedding 模型...")
    embedding_model = SentenceTransformer(str(MODEL))
    dimension = embedding_model.get_embedding_dimension()
    DB.parent.mkdir(parents=True, exist_ok=True)
    client = MilvusClient(str(DB))

    if client.has_collection(COLLECTION):
        client.drop_collection(COLLECTION)
    client.create_collection(
        collection_name=COLLECTION,
        dimension=dimension,
        metric_type="COSINE",
        auto_id=False,
    )

    rows = []
    row_id = 1
    for path in sorted(DOCS.glob("*.txt")):
        text = path.read_text(encoding="utf-8").strip()
        chunks = split_text(text)
        vectors = embedding_model.encode(chunks).tolist()
        for index, (chunk, vector) in enumerate(zip(chunks, vectors), start=1):
            rows.append({
                "id": row_id,
                "vector": vector,
                "content": chunk,
                "metadata": json.dumps({"source": path.name, "chunk": index}, ensure_ascii=False),
            })
            row_id += 1
        print(f"{path.name}: {len(chunks)} chunks")

    client.insert(collection_name=COLLECTION, data=rows)
    client.load_collection(collection_name=COLLECTION)
    print(f"完成：{len(rows)} 个 chunks")
    print(f"索引：{DB}")


if __name__ == "__main__":
    build_index()
