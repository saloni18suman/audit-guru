"""
RAG pipeline — loads expense_policy.txt into a FAISS vector store and provides
semantic search for policy context used by the Audit Agent.
"""

import os
import pickle
from langchain_community.document_loaders import TextLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import SentenceTransformerEmbeddings

POLICY_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "expense_policy.txt")
FAISS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "faiss_index")

_vectorstore = None


def _build_vectorstore() -> FAISS:
    embeddings = SentenceTransformerEmbeddings(model_name="all-MiniLM-L6-v2")

    if os.path.exists(FAISS_PATH):
        return FAISS.load_local(FAISS_PATH, embeddings, allow_dangerous_deserialization=True)

    loader = TextLoader(POLICY_PATH, encoding="utf-8")
    docs = loader.load()

    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = splitter.split_documents(docs)

    vectorstore = FAISS.from_documents(chunks, embeddings)
    vectorstore.save_local(FAISS_PATH)
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
