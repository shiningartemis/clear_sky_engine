from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """全应用业务表共享同一份元数据，跨模块外键不得各自建 Base。"""
