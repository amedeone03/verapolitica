from backend.app.services.ask_query_planner import (
    AskIntent,
    AskRetrieveMode,
    plan_ask_question,
)


def test_hybrid_planner_maps_paraphrases_keyword_does_not():
    question = "Quali promesse riguardano l'IRPEF?"
    hybrid = plan_ask_question(question, retrieve_mode=AskRetrieveMode.HYBRID)
    keyword = plan_ask_question(question, retrieve_mode=AskRetrieveMode.KEYWORD)
    assert hybrid.intent is AskIntent.PLEDGES_BY_TOPIC
    assert hybrid.topic_code == "1"
    assert hybrid.entity_query is None
    assert keyword.topic_code is None
    assert keyword.intent is AskIntent.POLITICIAN_PLEDGES
    assert "irpef" in (keyword.entity_query or "")


def test_ssn_and_pronto_soccorso_are_hybrid_health_paraphrases():
    for question in (
        "Quali promesse riguardano il SSN?",
        "Quali impegni riguardano il pronto soccorso?",
    ):
        hybrid = plan_ask_question(question, retrieve_mode=AskRetrieveMode.HYBRID)
        keyword = plan_ask_question(question, retrieve_mode=AskRetrieveMode.KEYWORD)
        assert hybrid.intent is AskIntent.PLEDGES_BY_TOPIC
        assert hybrid.topic_code == "3"
        assert keyword.topic_code is None


def test_keyword_still_detects_original_topic_words():
    plan = plan_ask_question(
        "Quali promesse riguardano le tasse?",
        retrieve_mode=AskRetrieveMode.KEYWORD,
    )
    assert plan.intent is AskIntent.PLEDGES_BY_TOPIC
    assert plan.topic_code == "1"
