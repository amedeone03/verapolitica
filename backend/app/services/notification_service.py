from datetime import date, timedelta
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models.civic import (
    NotificationChannel,
    NotificationEventType,
    NotificationReminderCandidate,
    NotificationSubscription,
    Referendum,
    ReferendumStatus,
)
from backend.app.schemas.civic import (
    NotificationSubscriptionResult,
    ReminderCandidateResult,
)


class NotificationServiceError(RuntimeError):
    pass


class NotificationValidationError(NotificationServiceError):
    pass


UPCOMING_WINDOW_DAYS = 14


class NotificationService:
    """Internal reminder candidates. No email, SMS, or push delivery."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def subscribe(
        self,
        *,
        destination_token: str,
        event_type: NotificationEventType,
        referendum_id: int | None = None,
        region_id: int | None = None,
        municipality_id: int | None = None,
    ) -> NotificationSubscriptionResult:
        token = destination_token.strip()
        if len(token) < 8 or len(token) > 64:
            raise NotificationValidationError(
                "destination_token must be 8–64 characters"
            )
        with self.session_factory() as session:
            with session.begin():
                existing = session.scalar(
                    select(NotificationSubscription).where(
                        NotificationSubscription.channel
                        == NotificationChannel.INTERNAL,
                        NotificationSubscription.destination_token == token,
                        NotificationSubscription.event_type == event_type,
                        NotificationSubscription.referendum_id == referendum_id,
                    )
                )
                if existing is None:
                    existing = NotificationSubscription(
                        channel=NotificationChannel.INTERNAL,
                        destination_token=token,
                        event_type=event_type,
                        referendum_id=referendum_id,
                        region_id=region_id,
                        municipality_id=municipality_id,
                        enabled=True,
                    )
                    session.add(existing)
                    session.flush()
                else:
                    existing.enabled = True
                    existing.region_id = region_id
                    existing.municipality_id = municipality_id
                session.refresh(existing)
                result = NotificationSubscriptionResult(
                    id=existing.id,
                    channel=existing.channel.value,
                    event_type=existing.event_type,
                    referendum_id=existing.referendum_id,
                    enabled=existing.enabled,
                )
        return result

    def list_subscriptions(self, *, destination_token: str) -> list[NotificationSubscriptionResult]:
        token = destination_token.strip()
        with self.session_factory() as session:
            rows = list(
                session.scalars(
                    select(NotificationSubscription).where(
                        NotificationSubscription.destination_token == token,
                        NotificationSubscription.enabled.is_(True),
                    )
                )
            )
            return [
                NotificationSubscriptionResult(
                    id=row.id,
                    channel=row.channel.value,
                    event_type=row.event_type,
                    referendum_id=row.referendum_id,
                    enabled=row.enabled,
                )
                for row in rows
            ]

    def list_inbox(self, *, destination_token: str, as_of: date | None = None) -> list[dict]:
        """Upcoming reminder candidates for referendums the reader subscribed to."""

        today = as_of or date.today()
        token = destination_token.strip()
        with self.session_factory() as session:
            subscribed = {
                row.referendum_id
                for row in session.scalars(
                    select(NotificationSubscription).where(
                        NotificationSubscription.destination_token == token,
                        NotificationSubscription.enabled.is_(True),
                        NotificationSubscription.referendum_id.is_not(None),
                    )
                )
                if row.referendum_id is not None
            }
            if not subscribed:
                return []
            candidates = list(
                session.scalars(
                    select(NotificationReminderCandidate)
                    .where(
                        NotificationReminderCandidate.referendum_id.in_(subscribed),
                        NotificationReminderCandidate.scheduled_for >= today,
                    )
                    .order_by(NotificationReminderCandidate.scheduled_for)
                    .limit(50)
                )
            )
            inbox: list[dict] = []
            for candidate in candidates:
                referendum = session.get(Referendum, candidate.referendum_id)
                if referendum is None or referendum.published_at is None:
                    continue
                inbox.append(
                    {
                        "event_type": candidate.event_type.value,
                        "referendum_id": referendum.id,
                        "title": referendum.title,
                        "scheduled_for": candidate.scheduled_for.isoformat(),
                        "vote_date": referendum.vote_date.isoformat(),
                    }
                )
            return inbox

    def unsubscribe(
        self, *, destination_token: str, referendum_id: int, event_type: NotificationEventType
    ) -> bool:
        token = destination_token.strip()
        with self.session_factory() as session:
            with session.begin():
                existing = session.scalar(
                    select(NotificationSubscription).where(
                        NotificationSubscription.destination_token == token,
                        NotificationSubscription.event_type == event_type,
                        NotificationSubscription.referendum_id == referendum_id,
                    )
                )
                if existing is None:
                    return False
                existing.enabled = False
                return True

    def generate_reminder_candidates(
        self, *, as_of: date | None = None
    ) -> ReminderCandidateResult:
        today = as_of or date.today()
        created = 0
        already_present = 0
        referendum_ids: list[int] = []
        with self.session_factory() as session:
            with session.begin():
                referendums = list(
                    session.scalars(
                        select(Referendum).where(
                            Referendum.published_at.is_not(None),
                            Referendum.status.in_(
                                (ReferendumStatus.SCHEDULED, ReferendumStatus.OPEN)
                            ),
                        )
                    )
                )
                for referendum in referendums:
                    keys = self._candidate_keys(referendum, today)
                    if not keys:
                        continue
                    referendum_ids.append(referendum.id)
                    for event_type, identity_key, scheduled_for in keys:
                        existing = session.scalar(
                            select(NotificationReminderCandidate).where(
                                NotificationReminderCandidate.identity_key
                                == identity_key
                            )
                        )
                        if existing is not None:
                            already_present += 1
                            continue
                        session.add(
                            NotificationReminderCandidate(
                                identity_key=identity_key,
                                event_type=event_type,
                                referendum_id=referendum.id,
                                scheduled_for=scheduled_for,
                            )
                        )
                        created += 1
                session.flush()
        return ReminderCandidateResult(
            created=created,
            already_present=already_present,
            referendum_ids=tuple(sorted(set(referendum_ids))),
        )

    @staticmethod
    def _candidate_keys(
        referendum: Referendum, today: date
    ) -> tuple[tuple[NotificationEventType, str, date], ...]:
        end = referendum.vote_end_date or referendum.vote_date
        keys: list[tuple[NotificationEventType, str, date]] = []
        upcoming_start = referendum.vote_date - timedelta(days=UPCOMING_WINDOW_DAYS)
        if upcoming_start <= today < referendum.vote_date:
            keys.append(
                (
                    NotificationEventType.REFERENDUM_UPCOMING,
                    _identity_key(
                        NotificationEventType.REFERENDUM_UPCOMING,
                        referendum.id,
                        referendum.vote_date,
                    ),
                    referendum.vote_date,
                )
            )
        if referendum.vote_date <= today <= end:
            keys.append(
                (
                    NotificationEventType.VOTING_DAY_REMINDER,
                    _identity_key(
                        NotificationEventType.VOTING_DAY_REMINDER,
                        referendum.id,
                        today,
                    ),
                    today,
                )
            )
        return tuple(keys)


def _identity_key(
    event_type: NotificationEventType, referendum_id: int, scheduled_for: date
) -> str:
    canonical = f"{event_type.value}:{referendum_id}:{scheduled_for.isoformat()}"
    return sha256(canonical.encode("utf-8")).hexdigest()
