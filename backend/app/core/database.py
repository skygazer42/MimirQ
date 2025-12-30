"""
数据库配置和会话管理模块

提供数据库连接、会话工厂和依赖注入功能。
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

# Create database engine
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ORM Base
Base = declarative_base()


def get_db():
    """Dependency: yield a DB session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
