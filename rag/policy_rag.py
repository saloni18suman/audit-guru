"""
RAG pipeline — loads expense_policy.txt from S3 (falls back to local file),
builds a FAISS vector store, and provides semantic search for the Audit Agent.
"""

import os
import tempfile
import boto3
from botocore.exceptions import ClientError
from langchain_community.document_loaders import TextLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import SentenceTransformerEmbeddings

_S3_BUCKET     = os.environ.get("S3_BUCKET_NAME",      "anomaguard-invoices")
_S3_POLICY_KEY = "config/expense_policy.txt"
_LOCAL_POLICY  = os.path.join(os.path.dirname(__file__), "..", "data", "expense_policy.txt")
_FAISS_PATH    = os.path.join(os.path.dirname(__file__), "..", "data", "faiss_index")

_vectorstore = None


def _download_policy_from_s3() -> str | None:
    """Download policy from S3 to a temp file. Returns path or None on failure."""
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=os.environ.get("S3_ENDPOINT_URL") or None,
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID") or None,
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY") or None,
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="wb")
        s3.download_fileobj(_S3_BUCKET, _S3_POLICY_KEY, tmp)
        tmp.close()
        print(f"[RAG] Policy loaded from S3: s3://{_S3_BUCKET}/{_S3_POLICY_KEY}")
        return tmp.name
    except ClientError as e:
        print(f"[RAG] S3 policy not found ({e}), falling back to local file.")
        return None
    except Exception as e:
        print(f"[RAG] S3 unavailable ({e}), falling back to local file.")
        return None


def _get_policy_path() -> str:
    s3_path = _download_policy_from_s3()
    if s3_path:
        return s3_path
    return _LOCAL_POLICY


def _build_vectorstore() -> FAISS:
    embeddings = SentenceTransformerEmbeddings(model_name="all-MiniLM-L6-v2")

    if os.path.exists(_FAISS_PATH):
        return FAISS.load_local(_FAISS_PATH, embeddings, allow_dangerous_deserialization=True)

    policy_path = _get_policy_path()
    loader = TextLoader(policy_path, encoding="utf-8")
    docs = loader.load()

    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = splitter.split_documents(docs)

    vectorstore = FAISS.from_documents(chunks, embeddings)
    vectorstore.save_local(_FAISS_PATH)
    return vectorstore


def get_policy_context(query: str, k: int = 4) -> str:
    global _vectorstore
    if _vectorstore is None:
        _vectorstore = _build_vectorstore()
    docs = _vectorstore.similarity_search(query, k=k)
    return "\n\n---\n\n".join(d.page_content for d in docs)


def reset_vectorstore():
    global _vectorstore
    _vectorstore = None
