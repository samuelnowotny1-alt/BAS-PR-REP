from bas_assistant.reasoning.sequence_parser import SequenceParser


def test_extract_point_refs_keeps_full_bas_refs_without_standalone_suffix_noise() -> None:
    parser = SequenceParser()

    refs = parser._extract_point_refs(
        "AHU-1 SF-CMD shall start on occupancy. AHU-1 SF-STS shall prove status."
    )

    assert refs == ["AHU-1 SF-CMD", "AHU-1 SF-STS"]


def test_extract_point_refs_does_not_treat_generic_status_words_as_points() -> None:
    parser = SequenceParser()

    refs = parser._extract_point_refs(
        "Supply fan command shall start on occupancy and status shall prove."
    )

    assert refs == []


def test_extract_point_refs_keeps_useful_process_abbreviations() -> None:
    parser = SequenceParser()

    refs = parser._extract_point_refs(
        "Maintain SAT setpoint at 55F and reset based on OAT."
    )

    assert refs == ["OAT", "SAT"]


def test_extract_point_refs_infers_occupancy_and_schedule_semantics() -> None:
    parser = SequenceParser()

    refs = parser._extract_point_refs(
        "During occupied hours, the unit runs on schedule. During unoccupied hours, the unit is off."
    )

    assert refs == ["OCC-MODE", "SCH"]


def test_extract_point_refs_infers_reheat_economizer_and_staging_semantics() -> None:
    parser = SequenceParser()

    refs = parser._extract_point_refs(
        "VAV-101 reheat valve command shall modulate. AHU-1 economizer dampers shall modulate. Boiler staging shall rotate lead lag weekly."
    )

    assert "VAV-101 HTG-CMD" in refs
    assert "AHU-1 DMP-CMD" in refs
    assert "AHU-1 LEAD-LAG" in refs or "VAV-101 LEAD-LAG" in refs
    assert "AHU-1 STAGE-CMD" in refs or "VAV-101 STAGE-CMD" in refs
