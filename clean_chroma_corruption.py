import os
import sys
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

from langchain_chroma import Chroma
from backend.rag.ingestion import get_embeddings
from langchain.storage import LocalFileStore
from langchain.storage._lc_store import create_kv_docstore
from backend.rag.ingestion import PARENT_STORE_DIR

def main():
    print("Connecting to Chroma...")
    vector_store = Chroma(
        persist_directory="./data/chroma_db",
        collection_name="icicos_sop",
        embedding_function=get_embeddings(),
    )
    
    raw_store = LocalFileStore(PARENT_STORE_DIR)
    docstore = create_kv_docstore(raw_store)
    
    print("Fetching all documents from ChromaDB...")
    data = vector_store.get()
    
    ids = data.get("ids", [])
    documents = data.get("documents", [])
    metadatas = data.get("metadatas", [])
    
    print(f"Total documents found in ChromaDB: {len(ids)}")
    
    to_delete_ids = []
    to_delete_sources = set()
    
    for doc_id, doc_text, meta in zip(ids, documents, metadatas):
        source = meta.get("source")
        if not source:
            print(f"Found chunk with no source metadata, marking for deletion. ID: {doc_id}")
            to_delete_ids.append(doc_id)
            continue
            
        # 1. Cek jika source mengandung karakter tidak aman (spasi, tanda kurung)
        # Karakter ini memicu InvalidKeyException di LocalFileStore
        has_invalid_chars = " " in source or "(" in source or ")" in source
        
        # 2. Cek jika parent document tidak ada di docstore (orphan)
        parent_id = meta.get("doc_id") or source
        is_orphan = False
        if parent_id:
            try:
                parent_docs = docstore.mget([parent_id])
                if not parent_docs or parent_docs[0] is None:
                    is_orphan = True
            except Exception:
                is_orphan = True
                
        if has_invalid_chars or is_orphan:
            reason = []
            if has_invalid_chars:
                reason.append("invalid characters in source name")
            if is_orphan:
                reason.append("orphan (no parent in docstore)")
                
            print(f"Marking for deletion: ID: {doc_id}, Source: '{source}', Reason: {', '.join(reason)}")
            to_delete_ids.append(doc_id)
            to_delete_sources.add(source)
            
    if not to_delete_ids:
        print("\nNo corrupt or orphaned documents found in ChromaDB.")
        return
        
    print(f"\nFound {len(to_delete_ids)} child chunks to delete (associated with {len(to_delete_sources)} sources).")
    
    # Hapus chunks dari ChromaDB berdasarkan ID
    print("Deleting chunks from ChromaDB...")
    vector_store.delete(ids=to_delete_ids)
    print("Deletion completed.")
    
    # Hapus juga file fisiknya dari parent store jika ada
    for source in to_delete_sources:
        from pathlib import Path
        parent_file = Path(PARENT_STORE_DIR) / source
        if parent_file.exists():
            try:
                parent_file.unlink()
                print(f"Deleted parent file: {parent_file}")
            except Exception as e:
                print(f"Failed to delete parent file {parent_file}: {e}")
                
    print("\nDatabase cleanup complete!")

if __name__ == "__main__":
    main()
