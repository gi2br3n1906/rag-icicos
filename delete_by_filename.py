import os
import sys
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

from langchain_chroma import Chroma
from backend.rag.ingestion import get_embeddings

def main():
    if len(sys.argv) < 2:
        print("Usage: python delete_by_filename.py <filename_in_chroma>")
        print("Contoh: python delete_by_filename.py \"SOP_Author_format_pdf (1)_1782721372.pdf\"")
        sys.exit(1)
        
    filename = sys.argv[1]
    print(f"Connecting to Chroma to delete file: '{filename}'...")
    
    vector_store = Chroma(
        persist_directory="./data/chroma_db",
        collection_name="icicos_sop",
        embedding_function=get_embeddings(),
    )
    
    # Hapus dari ChromaDB
    vector_store.delete(where={"source": filename})
    print("Delete from ChromaDB completed.")
    
    # Hapus juga dari parent store (jika ada file fisiknya)
    from backend.rag.ingestion import PARENT_STORE_DIR
    from pathlib import Path
    parent_file = Path(PARENT_STORE_DIR) / filename
    if parent_file.exists():
        parent_file.unlink()
        print(f"Parent document file '{parent_file}' deleted.")
    else:
        print("No parent document file found in parent store.")
        
    print("Done!")

if __name__ == "__main__":
    main()
