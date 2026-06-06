import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base

ContentTypeEnum = Enum(
    "filing", "article", "video", "newsletter", "website_page", "custom",
    name="content_type",
)

ProcessingStatusEnum = Enum(
    "pending", "processing", "completed", "failed", "skipped",
    name="processing_status",
)


class ContentItem(Base):
    __tablename__ = "content_items"
    __table_args__ = (
        UniqueConstraint("content_hash", name="unique_content_hash"),
        Index("idx_content_source_id", "source_id"),
        Index("idx_content_investor_id", "investor_id"),
        Index("idx_content_status", "processing_status", postgresql_where="processing_status IN ('pending', 'processing')"),
        Index("idx_content_published", "investor_id", "published_at"),
        Index("idx_content_type", "investor_id", "content_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    investor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("investors.id", ondelete="CASCADE"), nullable=False)
    content_type: Mapped[str] = mapped_column(ContentTypeEnum, nullable=False)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    cleaned_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    processing_status: Mapped[str] = mapped_column(ProcessingStatusEnum, nullable=False, default="pending")
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    source: Mapped["Source"] = relationship("Source", back_populates="content_items")
    investor: Mapped["Investor"] = relationship("Investor", back_populates="content_items")
    extracted_mentions: Mapped[list["ExtractedMention"]] = relationship("ExtractedMention", back_populates="content_item", cascade="all, delete-orphan")
    portfolio_changes: Mapped[list["PortfolioChange"]] = relationship("PortfolioChange", back_populates="content_item", cascade="all, delete-orphan")
