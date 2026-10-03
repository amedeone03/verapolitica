from scripts.run_ingestion import SOURCE_SPECS, parse_args


def test_ingestion_defaults_to_senato_for_backward_compatibility():
    assert parse_args([]).source == "senato"


def test_ingestion_accepts_camera_source():
    assert parse_args(["--source", "camera"]).source == "camera"
    assert SOURCE_SPECS["camera"].key == "camera-deputati"
