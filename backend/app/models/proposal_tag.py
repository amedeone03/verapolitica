"""Controlled tags on proposals.

Tags are never free text. ``topic`` values are Comparative Agendas Project
major topic codes (the same codes pledge classifications already use), so
topics stay comparable with political-science datasets. ``dossier`` values come
from a short editorial registry, for collections such as the budget law.
"""

from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProposalTagKind(StrEnum):
    TOPIC = "topic"
    DOSSIER = "dossier"


# CAP major topics (codes 11 and 22 are unused in the master codebook).
CAP_MAJOR_TOPICS: dict[str, str] = {
    "1": "Economia",
    "2": "Diritti civili",
    "3": "Sanità",
    "4": "Agricoltura",
    "5": "Lavoro",
    "6": "Istruzione",
    "7": "Ambiente",
    "8": "Energia",
    "9": "Immigrazione",
    "10": "Trasporti",
    "12": "Giustizia e criminalità",
    "13": "Welfare",
    "14": "Abitazione",
    "15": "Imprese",
    "16": "Difesa",
    "17": "Tecnologia e ricerca",
    "18": "Commercio estero",
    "19": "Affari internazionali",
    "20": "Governo e istituzioni",
    "21": "Territorio pubblico",
    "23": "Cultura",
}

DOSSIERS: dict[str, str] = {
    "legge_bilancio": "Legge di bilancio",
    "pnrr": "PNRR",
    "riforme_costituzionali": "Riforme costituzionali",
}


def tag_label(kind: ProposalTagKind, value: str) -> str | None:
    registry = CAP_MAJOR_TOPICS if kind is ProposalTagKind.TOPIC else DOSSIERS
    return registry.get(value)


class ProposalTag(Base):
    __tablename__ = "proposal_tags"
    __table_args__ = (
        UniqueConstraint("proposal_id", "kind", "value", name="uq_proposal_tags_value"),
        Index("ix_proposal_tags_kind_value", "kind", "value"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_id: Mapped[int] = mapped_column(
        ForeignKey("proposals.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[ProposalTagKind] = mapped_column(
        Enum(
            ProposalTagKind,
            native_enum=False,
            validate_strings=True,
            length=16,
            values_callable=lambda enum: [item.value for item in enum],
        )
    )
    value: Mapped[str] = mapped_column(String(64))
    assigned_by: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
