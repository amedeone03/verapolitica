from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.scoring.types import FulfillmentVerdict


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


MAX_ASK_QUESTION_LENGTH = 400


class AskRequest(_Frozen):
    question: str = Field(min_length=1, max_length=MAX_ASK_QUESTION_LENGTH)
    pledge_ids: tuple[int, ...] = Field(default=())

    @field_validator("question")
    @classmethod
    def _strip_question(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("question must not be blank")
        return stripped

    @field_validator("pledge_ids")
    @classmethod
    def _cap_pledge_ids(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        unique: list[int] = []
        seen: set[int] = set()
        for item in value:
            if item < 1:
                raise ValueError("pledge_ids must be positive")
            if item in seen:
                continue
            seen.add(item)
            unique.append(item)
            if len(unique) >= 12:
                break
        return tuple(unique)


class AskResultItem(_Frozen):
    type: str
    id: int
    title: str
    verdict: FulfillmentVerdict | None = None
    public_verdict_label: str | None = None
    url: str | None = None


class AskSource(_Frozen):
    title: str
    url: str
    excerpt: str


class AskResponse(_Frozen):
    answer: str
    intent: str
    entities: dict[str, str]
    results: tuple[AskResultItem, ...]
    sources: tuple[AskSource, ...]
    generated_by_ai: bool
    fallback: bool
    prompt_version: str
    model: str | None = None
