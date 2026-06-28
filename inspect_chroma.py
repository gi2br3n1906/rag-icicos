import os
import sys
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

from langchain_chroma import Chroma
from backend.rag.ingestion import get_embeddings

def main():
    print("Connecting to Chroma...")
    vectorstore = Chroma(
        persist_directory="./data/chroma_db",
        collection_name="icicos_sop",
        embedding_function=get_embeddings(),
    )
    
    print("Fetching documents...")
    data = vectorstore.get()
    
    ids = data.get("ids", [])
    documents = data.get("documents", [])
    metadatas = data.get("metadatas", [])
    
    print(f"Total documents found: {len(ids)}")
    
    corrupt_count = 0
    for idx, (doc_id, doc_text, meta) in enumerate(zip(ids, documents, metadatas)):
        if doc_text is None:
            print(f"[!] Corrupt doc found! Index: {idx}, ID: {doc_id}, Meta: {meta}")
            corrupt_count += 1
        else:
            print(f"[{idx}] ID: {doc_id}, Text length: {len(doc_text)}, Meta: {meta}")
            
    print(f"\nScan complete. Corrupt documents count: {corrupt_count}")

if __name__ == "__main__":
    main()
