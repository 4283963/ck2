#!/usr/bin/env python3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.database import init_db, engine, Base
from common.models import Photo, Detection, Group, PhotoGroup

if __name__ == "__main__":
    print("Initializing database tables...")
    print(f"Database URL: {engine.url}")
    init_db()
    tables = list(Base.metadata.tables.keys())
    print(f"Database tables created successfully! ({len(tables)} tables)")
    for t in sorted(tables):
        print(f"  - {t}")
