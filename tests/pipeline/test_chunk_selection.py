from dataclasses import dataclass

from backend.app.pipeline.chunk_selection import (
    CHUNK_SELECTION_VERSION,
    EXTRACTION_PURPOSE_ARTICLES,
    EXTRACTION_PURPOSE_CANONICAL,
    TIER_METADATA,
    TIER_SUBSTANCE,
    TIER_SUPPORTING,
    classify_chunk,
    coverage_note_from_payload,
    estimate_tokens,
    has_sufficient_canonical_coverage,
    is_near_duplicate,
    pack_chunks_for_context,
    preview_chunk_selection_details,
    score_chunk,
    select_relevant_chunks,
)


@dataclass(frozen=True)
class _Chunk:
    chunk_index: int
    text: str
    page_start: int | None
    page_end: int | None


_DOSSIER_NAV = (
    "Disegni di legge Atto Senato n. 99 XIX Legislatura Dati generali- Testi ed "
    "emendamenti- Dossier- Trattazione in Commissione- Trattazione in consultiva- "
    "Trattazione in Assemblea- "
)
_TRANSCRIPT = (
    "IN SEDE CONSULTIVA. Il PRESIDENTE invita i senatori. Applausi. "
    "Discussione generale. Il seguito dell'esame è, quindi, rinviato. "
    "Ricorda che il disegno di legge, d'iniziativa governativa e già approvato, "
    "è all'esame della Commissione permanente. Resoconto sommario della seduta. "
)


def _parliamentary_chunks() -> tuple[_Chunk, ...]:
    chunks = [
        _Chunk(
            0,
            "Fascicolo Iter DDL S. 99\n"
            "Conversione in legge del decreto-legge 1 gennaio 2026, n. 1, recante "
            "disposizioni urgenti",
            1,
            1,
        ),
        _Chunk(
            1,
            "Indice\n1.1. Dati generali 2\n1.2. Testi 5\n"
            + (
                "1.4.2.1.1. 5^ Commissione permanente (Bilancio) - Seduta n. 608 411\n"
                * 8
            ),
            2,
            2,
        ),
        _Chunk(
            2,
            "1.4.2.6.1. 9^ Commissione permanente (Industria) - Seduta n. 330 850\n"
            * 10,
            3,
            3,
        ),
        _Chunk(3, "DDL S. 99 - Senato della Repubblica XIX Legislatura Pag. 1", 4, 4),
        _Chunk(
            4,
            "1.1. Dati generali collegamento al documento su www.senato.it\n"
            f"{_DOSSIER_NAV}"
            "Conversione in legge del decreto-legge 1 gennaio 2026, n. 1 "
            "Iter 30 settembre 2026: approvato definitivamente, non ancora pubblicato "
            "Iniziativa Governativa Pres. Consiglio Giorgia Meloni "
            "(Governo Meloni-I) Ministro dell'interno Matteo Rossi "
            "Presentazione Trasmesso in data 28 settembre 2026; "
            "annunciato nella seduta n. 459 del 29 settembre 2026. "
            "Classificazione TESEO",
            5,
            5,
        ),
        _Chunk(
            6,
            "Relatori Relatore alla Commissione Sen. Bianchi. "
            "Assegnazione Assegnato alla 5ª Commissione permanente (Bilancio) "
            "in sede referente il 29 settembre 2026. "
            "Annuncio nella seduta n. 459 del 29 settembre 2026.",
            7,
            7,
        ),
        _Chunk(
            8,
            "DISEGNO DI LEGGE presentato dal Presidente del Consiglio dei ministri "
            "(MELONI) Art. 1. Il decreto-legge 1 gennaio 2026, n. 1, è convertito "
            "in legge. Si impegna a stanziare 10 milioni di euro il 12/01/2026.",
            9,
            9,
        ),
        _Chunk(
            9,
            "Art. 1. 2. La presente legge entra in vigore il giorno successivo. "
            "Si autorizza la spesa di 10 milioni di euro.",
            10,
            10,
        ),
    ]
    for index in range(20, 90):
        chunks.append(
            _Chunk(
                index,
                _TRANSCRIPT + f" pagina {index} " + ("testo commissione " * 40),
                index * 10,
                index * 10,
            )
        )
    return tuple(chunks)


def test_short_document_keeps_full_coverage():
    chunks = tuple(
        _Chunk(index, f"Articolo {index} testo", 1, 1) for index in range(4)
    )
    selection = select_relevant_chunks(chunks, max_selected=16)
    assert selection.full_document_coverage is True
    assert selection.selected_indexes == (0, 1, 2, 3)
    assert selection.page_count == 1
    assert "full extracted document" in selection.coverage_note()


def test_long_document_preserves_pages_and_caps_selected_chunks():
    chunks = []
    chunks.append(
        _Chunk(
            0,
            "Disegno di legge. Atto Senato. Dati generali. Presentato da Governo.",
            1,
            1,
        )
    )
    chunks.append(_Chunk(1, "Relatori e Assegnazione all'iter in commissione.", 2, 2))
    chunks.append(_Chunk(2, "Introduzione procedurale senza impegni.", 3, 3))
    for index in range(3, 80):
        chunks.append(
            _Chunk(index, f"Pagina descrittiva numero {index} senza termini.", index + 1, index + 1)
        )
    chunks.append(
        _Chunk(
            80,
            "Articolo 12. Si impegna a stanziare 10 milioni di euro il 12/01/2026.",
            1188,
            1188,
        )
    )
    selection = select_relevant_chunks(
        tuple(chunks),
        max_selected=16,
        extraction_purpose=EXTRACTION_PURPOSE_ARTICLES,
    )
    assert selection.full_document_coverage is False
    assert selection.method == CHUNK_SELECTION_VERSION
    assert selection.page_count == 1188
    assert selection.total_chunk_count == 81
    assert 4 <= len(selection.selected_indexes) <= 16
    assert 0 in selection.selected_indexes
    assert 1 in selection.selected_indexes
    assert 80 in selection.selected_indexes
    selected_pages = {chunk.page_start for chunk in selection.chunks}
    assert 1 in selected_pages
    assert 1188 in selected_pages
    assert chunks[40].chunk_index not in selection.selected_indexes
    note = selection.coverage_note()
    assert "selected evidence section" in note
    assert "1,188-page document" in note
    payload = selection.as_dict()
    assert payload["selected_chunk_indexes"] == list(selection.selected_indexes)
    assert payload["full_document_coverage"] is False
    assert coverage_note_from_payload(payload) == note
    assert payload["preview"]


def test_relevance_scoring_prefers_schema_terms_money_and_dates():
    weak = score_chunk("pagina descrittiva senza contenuto utile")
    strong = score_chunk(
        "Disegno di legge presentato da Governo. Articolo 1. 12/01/2026. 5 milioni di euro."
    )
    assert strong > weak
    assert strong > 20


def test_token_budget_packs_high_value_chunks_and_records_omissions():
    filler = ("articolo descrittivo senza impegno. " * 80)
    chunks = [
        _Chunk(0, "Disegno di legge. Atto Senato. Dati generali. Presentato da Governo. " + filler, 1, 1),
        _Chunk(1, "Relatori e Assegnazione. " + filler, 2, 2),
        _Chunk(2, "Introduzione procedurale. " + filler, 3, 3),
    ]
    for index in range(3, 16):
        chunks.append(_Chunk(index, f"Pagina debole {index}. {filler}", index + 1, index + 1))
    chunks.append(
        _Chunk(
            16,
            "Articolo 12. Si impegna a stanziare 10 milioni di euro il 12/01/2026. " + filler,
            1188,
            1188,
        )
    )
    selection = select_relevant_chunks(
        tuple(chunks),
        max_selected=16,
        max_document_tokens=4_500,
        extraction_purpose=EXTRACTION_PURPOSE_ARTICLES,
    )
    sent = set(selection.sent_indexes)
    omitted = set(selection.omitted_indexes)
    assert 0 in sent
    assert 16 in sent
    assert selection.document_token_estimate <= 4_500 or len(sent) == 1
    assert omitted
    assert not sent.intersection(omitted)
    assert set(selection.selected_indexes) == sent | omitted
    assert [chunk.chunk_index for chunk in selection.chunks] == list(selection.sent_indexes)
    note = selection.coverage_note()
    assert "packed evidence section" in note
    assert "omitted to fit the local context budget" in note
    assert selection.as_dict()["omitted_chunk_indexes"] == list(selection.omitted_indexes)


def test_pack_chunks_skips_later_chunks_that_exceed_remaining_budget():
    small = _Chunk(0, "Disegno di legge. Presentato da Governo.", 1, 1)
    huge = _Chunk(1, "Articolo 1. " + ("impegno finanziario euro " * 400), 10, 10)
    packed, used = pack_chunks_for_context((small, huge), max_document_tokens=200)
    assert [chunk.chunk_index for chunk in packed] == [0]
    assert used == estimate_tokens(
        "--- CHUNK 0 (pages 1-1) ---\nDisegno di legge. Presentato da Governo."
    )


def test_metadata_chunks_outrank_late_commission_transcripts():
    chunks = _parliamentary_chunks()
    selection = select_relevant_chunks(
        chunks, max_selected=16, max_document_tokens=4_500
    )
    sent = set(selection.sent_indexes)
    assert 4 in sent
    assert 0 in sent
    assert 20 not in sent
    assert 9 not in sent
    assert 80 not in sent
    sent_text = "\n".join(chunk.text for chunk in selection.chunks)
    assert "Iniziativa Governativa" in sent_text
    assert "approvato definitivamente" in sent_text
    assert "Pres. Consiglio Giorgia Meloni" in sent_text
    assert "Fascicolo Iter DDL" in sent_text or "presentato dal Presidente" in sent_text
    preview_by_index = {row.chunk_index: row for row in selection.preview}
    assert preview_by_index[4].tier == TIER_METADATA
    assert preview_by_index[4].page == 5
    assert classify_chunk(chunks[1].text)[0] == TIER_SUPPORTING
    assert classify_chunk(chunks[20].text)[0] != TIER_METADATA


def test_initiative_status_title_and_actors_are_retained():
    chunks = _parliamentary_chunks()
    selection = select_relevant_chunks(
        chunks, max_selected=16, max_document_tokens=4_500
    )
    sent_text = "\n".join(chunk.text for chunk in selection.chunks)
    assert "Conversione in legge del decreto-legge 1 gennaio 2026" in sent_text
    assert "Iniziativa Governativa" in sent_text
    assert "Iter 30 settembre 2026" in sent_text
    assert "Giorgia Meloni" in sent_text
    assert 9 not in selection.sent_indexes
    summary = selection.as_dict()["evidence_summary"]
    assert "Government initiative" in summary
    assert "Metadata / status" in summary
    assert "Legislative text" not in summary


def test_token_budget_is_respected_for_parliamentary_selection():
    chunks = _parliamentary_chunks()
    selection = select_relevant_chunks(
        chunks, max_selected=16, max_document_tokens=4_500
    )
    assert selection.document_token_estimate <= 3_000
    assert selection.max_document_tokens == 4_500
    assert 1 <= len(selection.sent_indexes) <= 4
    metadata_sent = [
        row for row in selection.preview if row.sent and row.tier == TIER_METADATA
    ]
    substance_sent = [
        row for row in selection.preview if row.sent and row.tier == TIER_SUBSTANCE
    ]
    assert 1 <= len(metadata_sent) <= 4
    assert substance_sent == []


def test_duplicate_chunks_do_not_waste_budget():
    original = _Chunk(
        0,
        "1.1. Dati generali\nIniziativa Governativa Pres. Consiglio Giorgia Meloni "
        "Iter 30 settembre 2026: approvato definitivamente",
        5,
        5,
    )
    duplicate = _Chunk(1, original.text, 6, 6)
    law = _Chunk(
        2,
        "DISEGNO DI LEGGE presentato dal Presidente del Consiglio Art. 1. "
        "Si impegna a stanziare 10 milioni di euro.",
        9,
        9,
    )
    filler = [
        _Chunk(index, f"pagina descrittiva {index} senza termini utili", index, index)
        for index in range(3, 30)
    ]
    assert is_near_duplicate(original.text, duplicate.text)
    selection = select_relevant_chunks(
        (original, duplicate, law, *filler),
        max_selected=16,
        max_document_tokens=4_500,
    )
    sent = set(selection.sent_indexes)
    assert 0 in sent
    assert 1 not in sent
    article_claims = select_relevant_chunks(
        (original, duplicate, law, *filler),
        max_selected=16,
        max_document_tokens=4_500,
        extraction_purpose=EXTRACTION_PURPOSE_ARTICLES,
    )
    assert 2 in article_claims.sent_indexes


def test_page_numbers_are_preserved_in_preview():
    chunks = _parliamentary_chunks()
    payload = preview_chunk_selection_details(
        chunks, max_selected=16, max_document_tokens=4_500
    )
    by_index = {row["chunk_index"]: row for row in payload["preview"]}
    assert by_index[4]["page"] == 5
    sent_pages = payload.get("sent_pages") or payload["selected_pages"]
    assert 5 in sent_pages
    assert 11 not in sent_pages
    assert 12 not in sent_pages
    assert payload["method"] == CHUNK_SELECTION_VERSION
    assert payload["extraction_purpose"] == EXTRACTION_PURPOSE_CANONICAL


def test_table_of_contents_is_not_mandatory_metadata():
    toc = "Indice\n1.1. Dati generali 2\n1.2. Testi 5\n" + (
        "1.3.2.1.1. 5^ Commissione permanente (Bilancio) - Seduta n. 608 411\n" * 6
    )
    dati = (
        "1.1. Dati generali\nIniziativa Governativa Pres. Consiglio Giorgia Meloni "
        "Iter 1 gennaio 2026: approvato definitivamente"
    )
    assert classify_chunk(toc)[0] == TIER_SUPPORTING
    assert classify_chunk(dati)[0] == TIER_METADATA
    assert "toc" in classify_chunk(toc)[1]


def test_prose_presentazione_is_not_metadata_heading():
    prose = (
        "presentazione di istanza di sanatoria, pena improcedibilità dell'istanza. "
        "L'interessato è ammesso con riserva."
    )
    heading = (
        "Presentazione Trasmesso in data 28 settembre 2026. "
        "Iniziativa Governativa Pres. Consiglio Giorgia Meloni "
        "Iter 30 settembre 2026: approvato definitivamente"
    )
    sitting = (
        "2ª Commissione permanente (GIUSTIZIA) MERCOLEDÌ 30 SETTEMBRE 2026 "
        "Presidenza del Vice Presidente SISLER La seduta inizia alle ore 9,40. "
        "IN SEDE CONSULTIVA (2047) Conversione in legge. Disegno di legge. Articolo 1. "
        "10 milioni di euro."
    )
    assert classify_chunk(prose)[0] != TIER_METADATA
    assert classify_chunk(heading)[0] == TIER_METADATA
    assert classify_chunk(sitting)[0] == TIER_SUPPORTING


def test_subject_catalog_does_not_outrank_legislative_text():
    catalog = "PUBBLICO IMPIEGO (Art.1), FERIE (Art.1), " + ", ".join(
        f"TEMA {index} (Art.{index})" for index in range(2, 20)
    )
    law = (
        "DISEGNO DI LEGGE presentato dal Presidente del Consiglio Art. 1. "
        "Il decreto-legge è convertito in legge."
    )
    assert classify_chunk(catalog)[0] == TIER_SUPPORTING
    assert classify_chunk(law)[0] == TIER_METADATA
    chunks = tuple(
        _Chunk(index, f"riempimento {index} senza termini", index, index)
        for index in range(20)
    )
    chunks = (
        _Chunk(0, catalog, 6, 6),
        _Chunk(1, law, 9, 9),
        *chunks[2:],
    )
    selection = select_relevant_chunks(chunks, max_selected=16, max_document_tokens=4_500)
    assert 1 in selection.sent_indexes


def test_canonical_proposal_stops_after_sufficient_metadata_coverage():
    chunks = _parliamentary_chunks()
    selection = select_relevant_chunks(
        chunks, max_selected=16, max_document_tokens=4_500
    )
    sent = set(selection.sent_indexes)
    assert selection.extraction_purpose == EXTRACTION_PURPOSE_CANONICAL
    assert selection.sent_chunk_policy_version == "canonical_metadata_pack_v1"
    assert selection.parliamentary_bill is True
    assert has_sufficient_canonical_coverage(set(selection.canonical_coverage))
    assert 4 in sent
    assert 0 in sent
    assert 9 not in sent
    assert selection.document_token_estimate < 3_000
    substance_sent = [
        row for row in selection.preview if row.sent and row.tier == TIER_SUBSTANCE
    ]
    assert substance_sent == []
    note = selection.coverage_note()
    assert "Full document:" in note
    assert "relevant metadata section" in note


def test_canonical_proposal_does_not_fill_unused_budget_with_substance():
    chunks = _parliamentary_chunks()
    selection = select_relevant_chunks(
        chunks, max_selected=16, max_document_tokens=4_500
    )
    unused = 4_500 - selection.document_token_estimate
    assert unused > 500
    assert all(row.tier != TIER_SUBSTANCE or not row.sent for row in selection.preview)
    article_claims = select_relevant_chunks(
        chunks,
        max_selected=16,
        max_document_tokens=4_500,
        extraction_purpose=EXTRACTION_PURPOSE_ARTICLES,
    )
    assert article_claims.sent_chunk_policy_version == "proximity_token_pack_v1"
    assert 9 in article_claims.selected_indexes


def test_canonical_metadata_selection_does_not_hardcode_pages():
    fillers = tuple(
        _Chunk(index, f"pagina descrittiva {index} senza termini utili", index, index)
        for index in range(50, 80)
    )
    chunks = (
        _Chunk(10, "Fascicolo Iter DDL S. 12 titolo ufficiale della proposta", 40, 40),
        _Chunk(
            22,
            "1.1. Dati generali Iniziativa Governativa Governo Meloni-I "
            "Iter 1 gennaio 2026: approvato definitivamente "
            "Presentazione Trasmesso in data 2 gennaio 2026.",
            88,
            88,
        ),
        _Chunk(
            40,
            "Art. 14. Si autorizza la spesa di 10 milioni di euro per modifiche.",
            200,
            200,
        ),
        *fillers,
    )
    selection = select_relevant_chunks(
        chunks, max_selected=16, max_document_tokens=4_500
    )
    sent_pages = {row.page for row in selection.preview if row.sent}
    assert 40 in sent_pages
    assert 88 in sent_pages
    assert 200 not in sent_pages
    assert 11 not in sent_pages
    assert 12 not in sent_pages
