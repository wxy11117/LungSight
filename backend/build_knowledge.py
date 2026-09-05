from pathlib import Path

from knowledge import build_knowledge_base


BASE_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = BASE_DIR.parent.parent
DATABASE_PATH = BASE_DIR / "data" / "lungsight.sqlite3"


if __name__ == "__main__":
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    result = build_knowledge_base(DATABASE_PATH, WORKSPACE_ROOT, force=True)
    print(f"Knowledge base ready: {result['sources']} sources, {result['chunks']} chunks")
