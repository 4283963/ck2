#!/usr/bin/env python3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.database import init_db, engine, Base
from common.models import Photo, Detection

if __name__ == "__main__":
    print("Initializing database tables...")
    print(f"Database URL: {engine.url}")
    init_db()
    print("Database tables created successfully!")
    print(f"Tables: {list(Base.metadata.tables.keys())}")
