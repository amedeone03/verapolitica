from backend.app.services.government_offices import (
    cabinet_office,
    government_office_rank,
    has_government_office,
    is_government_office,
)


def test_governo_it_titles_rank_as_cabinet_offices():
    assert government_office_rank("Presidente del Consiglio") == 0
    assert government_office_rank("Vice Presidente del Consiglio") == 1
    assert government_office_rank("Ministro") == 2
    assert government_office_rank("Ministro senza portafoglio") == 3
    assert government_office_rank("Sottosegretario") == 4
    assert government_office_rank("deputy") > 4
    assert is_government_office("presidente del consiglio")
    assert not is_government_office("senator")


def test_cabinet_office_prefers_government_over_a_later_camera_seat():
    mandates = (
        {
            "office": "deputy",
            "start_date": "2022-10-13",
            "end_date": None,
        },
        {
            "office": "Presidente del Consiglio",
            "start_date": "2022-10-21",
            "end_date": None,
        },
        {
            "office": "deputy",
            "start_date": "2024-03-01",
            "end_date": None,
        },
    )
    assert has_government_office(mandates)
    assert cabinet_office(mandates) == "Presidente del Consiglio"
    assert cabinet_office(({"office": "senator", "end_date": None},)) is None
