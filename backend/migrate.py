from .db import Database
from .config import get_settings

if __name__ == "__main__":
    Database(get_settings().database_path).initialize()
    print("SQLite schema is up to date")
