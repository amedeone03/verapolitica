from backend.app.models.proposal import ProposalActorRole, ProposalStatus, ProposalType
from backend.app.public_labels import (
    PROPOSAL_STATUS_LABELS,
    public_proposal_actor_role_label,
    public_proposal_status_label,
    public_proposal_type_label,
    public_referendum_status_label,
    public_referendum_type_label,
    public_scope_type_label,
)


def test_proposal_status_enum_values_stay_internal():
    assert [item.value for item in ProposalStatus] == [
        "announced",
        "introduced",
        "assigned",
        "under_review",
        "approved",
        "rejected",
        "withdrawn",
        "enacted",
        "completed",
        "superseded",
        "lapsed",
        "returned",
    ]
    assert ProposalType.EXPLICIT_PROMISE.value == "explicit_promise"
    assert ProposalActorRole.COMMITMENT_OWNER.value == "commitment_owner"


def test_citizen_facing_proposal_labels_are_italian():
    assert public_proposal_status_label("introduced") == "Presentata"
    assert public_proposal_status_label(ProposalStatus.APPROVED) == "Approvata"
    assert public_proposal_status_label(ProposalStatus.REJECTED) == "Respinta"
    assert public_proposal_type_label("explicit_promise") == "Promessa esplicita"
    assert public_proposal_actor_role_label("commitment_owner") == "Titolare della promessa"
    assert set(PROPOSAL_STATUS_LABELS) == {item.value for item in ProposalStatus}


def test_citizen_facing_civic_labels_are_italian():
    assert public_referendum_type_label("national_abrogative") == "abrogativo nazionale"
    assert public_referendum_status_label("scheduled") == "in programma"
    assert public_scope_type_label("municipality") == "comunale"
