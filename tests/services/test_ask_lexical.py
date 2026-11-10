from backend.app.services.ask_lexical import (
    lexical_overlap,
    sort_pledge_ids,
    unique_paraphrase_match,
)


def test_hospital_paraphrase_overlaps_waiting_lists():
    question = "Quali promesse riguardano i tempi in ospedale?"
    waiting = lexical_overlap(
        question,
        "Ridurre le liste di attesa",
        "Ridurremo i tempi delle liste di attesa negli ospedali.",
    )
    pensions = lexical_overlap(
        question,
        "Aumentare le pensioni minime",
        "Aumenteremo le pensioni minime a 1.000 euro al mese.",
    )
    assert waiting >= 2
    assert waiting > pensions


def test_unique_paraphrase_match_requires_clear_winner():
    question = "tempi in ospedale"
    winner = unique_paraphrase_match(
        question=question,
        candidates=[
            (1, "Ridurre le liste di attesa", "liste di attesa negli ospedali"),
            (2, "Aumentare le pensioni minime", "pensioni minime a 1000 euro"),
        ],
    )
    assert winner == 1
    tied = unique_paraphrase_match(
        question=question,
        candidates=[
            (1, "liste di attesa in ospedale", None),
            (2, "tempi di attesa in ospedale", None),
        ],
    )
    assert tied is None


def test_sort_keeps_original_order_when_scores_tie():
    assert sort_pledge_ids(
        ordered_ids=[10, 11, 12],
        overlaps={10: 0, 11: 0, 12: 0},
        fts_ranks={},
    ) == [10, 11, 12]
    assert sort_pledge_ids(
        ordered_ids=[10, 11, 12],
        overlaps={10: 1, 11: 3, 12: 1},
        fts_ranks={10: 0.9},
    ) == [11, 10, 12]
