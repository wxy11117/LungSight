"""Create a consistent local SQLite backup before additive application migrations."""
from contextlib import closing
from datetime import datetime
import os
from pathlib import Path
import sqlite3


def main() -> None:
    data = Path(os.environ.get("LUNGSIGHT_DATA_DIR", str(Path(__file__).resolve().parent / "data"))).resolve()
    source = data / "lungsight.sqlite3"
    if not source.is_file():
        raise FileNotFoundError("No existing LungSight database to back up")
    directory = data / "backups"
    directory.mkdir(exist_ok=True)
    destination = directory / f"lungsight-before-history-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3"
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as reader:
        with closing(sqlite3.connect(destination)) as backup:
            reader.backup(backup)
            if backup.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup integrity check failed")
    print(f"Verified backup: {destination.name}")


if __name__ == "__main__":
    main()
