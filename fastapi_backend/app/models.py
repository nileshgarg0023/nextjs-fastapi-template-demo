from fastapi_users.db import SQLAlchemyBaseUserTableUUID
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, String, Integer, ForeignKey
from sqlalchemy.orm import relationship
from fastapi_users_db_sqlalchemy.generics import GUID
from uuid import uuid4


class Base(DeclarativeBase):
    pass


class User(SQLAlchemyBaseUserTableUUID, Base):
    items = relationship("Item", back_populates="user", cascade="all, delete-orphan")
    gmail_connections = relationship(
        "GmailConnection", back_populates="user", cascade="all, delete-orphan"
    )


class Item(Base):
    __tablename__ = "items"

    id = Column(GUID, primary_key=True, default=uuid4)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    quantity = Column(Integer, nullable=True)
    user_id = Column(GUID, ForeignKey("user.id"), nullable=False)

    user = relationship("User", back_populates="items")


class GmailConnection(Base):
    __tablename__ = "gmail_connections"

    id = Column(GUID, primary_key=True, default=uuid4)
    user_id = Column(GUID, ForeignKey("user.id"), nullable=False)
    email_address = Column(String, nullable=False, index=True, unique=True)
    access_token = Column(String, nullable=False)
    refresh_token = Column(String, nullable=True)
    history_id = Column(String, nullable=True)
    watch_expiration = Column(String, nullable=True)
    categories = Column(String, nullable=False, default="primary,promotions,updates")

    user = relationship("User", back_populates="gmail_connections")
