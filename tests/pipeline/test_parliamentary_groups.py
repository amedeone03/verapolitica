import json
from datetime import date
from pathlib import Path

from backend.app.pipeline.collectors.base import encode_sparql_bundle
from backend.app.pipeline.mappers import (
    CameraParliamentaryGroupMapper,
    SenatoParliamentaryGroupMapper,
)
from backend.app.pipeline.parsers import CameraParser, SenatoParser


def bundle(schema: str, people_path: str, groups_path: str) -> bytes:
    return encode_sparql_bundle(
        schema=schema,
        people_response=Path(people_path).read_bytes(),
        parliamentary_groups_response=Path(groups_path).read_bytes(),
    )


def test_camera_group_parser_and_mapper_normalize_official_fields():
    parsed = CameraParser().parse(
        bundle(
            "verapolitica_camera_bundle_v1",
            "data/fixtures/camera/camera_deputies.json",
            "data/fixtures/camera/camera_groups.json",
        )
    )

    assert len(parsed.parliamentary_group_records) == 1
    record = parsed.parliamentary_group_records[0]
    assert record["membership_start"] == "2022-10-18"
    observation = CameraParliamentaryGroupMapper(19).map_records(
        (record,), source_key="camera-deputati", raw_document_id=7
    )[0]
    assert observation.canonical_name == "GRUPPO X"
    assert observation.abbreviation == "GX"
    assert observation.institution == "Camera dei Deputati"
    assert observation.legislature == "19"
    assert observation.start_date == date(2022, 10, 18)
    assert str(observation.source_url).endswith("d100_19")


def test_senato_group_parser_and_mapper_preserve_role_and_legislature():
    parsed = SenatoParser().parse(
        bundle(
            "verapolitica_senato_bundle_v1",
            "data/fixtures/demo/senato_demo.json",
            "data/fixtures/senato/senato_groups.json",
        )
    )

    assert len(parsed.parliamentary_group_records) == 1
    record = parsed.parliamentary_group_records[0]
    observation = SenatoParliamentaryGroupMapper().map_records(
        (record,), source_key="senato-repubblica", raw_document_id=8
    )[0]
    assert observation.canonical_name == "Gruppo X"
    assert observation.abbreviation == "GX"
    assert observation.institution == "Senato della Repubblica"
    assert observation.legislature == "19"
    assert observation.role == "Membro"
    assert observation.start_date == date(2022, 10, 18)


def test_group_records_participate_in_canonical_change_detection():
    initial = CameraParser().parse(
        bundle(
            "verapolitica_camera_bundle_v1",
            "data/fixtures/camera/camera_deputies.json",
            "data/fixtures/camera/camera_groups.json",
        )
    )
    updated = CameraParser().parse(
        bundle(
            "verapolitica_camera_bundle_v1",
            "data/fixtures/camera/camera_deputies.json",
            "data/fixtures/camera/camera_groups_updated.json",
        )
    )

    assert initial.canonical_json != updated.canonical_json
    assert len(json.loads(updated.canonical_json)["parliamentary_groups"]) == 2
