"""engine.py"""

import os
import logging
import sys
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

DB_PATH = "./data/mutual_aid.db"
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH.lstrip('./')}"

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("Database")

engine = create_async_engine(DATABASE_URL, echo=False)
