from backend.app.services.feed_service import stage_for


def states(status):
    return [step["state"] for step in stage_for(status)["steps"]]


def test_stage_strip_follows_the_legislative_path():
    assert states("introduced") == ["current", "todo", "todo", "todo"]
    assert states("assigned") == ["done", "current", "todo", "todo"]
    assert states("approved") == ["done", "done", "current", "todo"]
    assert states("enacted") == ["done", "done", "done", "done"]
    rejected = stage_for("rejected")
    assert rejected["stopped"] and [s["state"] for s in rejected["steps"]][1] == "stopped"
    assert stage_for(None) is None
