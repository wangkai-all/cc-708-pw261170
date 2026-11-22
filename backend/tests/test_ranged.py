"""Range segmentation, receiver assembly and fault diagnosis."""

import pytest

from ldap_console.ranged import (
    DemoRangeService,
    RangeAssembler,
    RangeFault,
    RangeTag,
    describe_coverage,
)


def _values(n: int) -> list[bytes]:
    return [f"v{i:02d}".encode() for i in range(n)]


def test_range_tag_parse_open_and_closed():
    assert RangeTag.parse("member;range=0-*") == RangeTag(0, None)
    assert RangeTag.parse("member;range=3-9") == RangeTag(3, 9)
    with pytest.raises(ValueError):
        RangeTag.parse("member")


def test_service_segments_only_above_threshold():
    svc = DemoRangeService(page_size=3, threshold=4)
    assert svc.should_segment("member", 5)
    assert not svc.should_segment("member", 4)
    assert not svc.should_segment("cn", 100)  # not a ranged attribute


def test_full_range_conversation_assembles_all_values():
    svc = DemoRangeService(page_size=3, threshold=4)
    full = _values(10)

    def fetcher(tag: str):
        option = tag if "range=" in tag else None
        return svc.serve("member", full, option)

    result = RangeAssembler(fetcher).fetch("member")
    assert result.complete
    assert not result.faults
    assert result.values == full
    # 10 values, page 3 -> segments of 3,3,3,1 with a concrete final bound.
    tags = [s.response_tag for s in result.segments]
    assert tags == [
        "member;range=0-*",
        "member;range=3-*",
        "member;range=6-*",
        "member;range=9-9",
    ]
    coverage = describe_coverage(result.segments)
    assert coverage["missing_indices"] == []
    assert coverage["total_values"] == 10
    assert coverage["last_index"] == 9


def test_non_segmented_service_returns_complete_attribute():
    full = _values(2)

    def fetcher(_tag: str):
        return "member", full  # plain tag, no range option

    result = RangeAssembler(fetcher).fetch("member")
    assert result.complete and result.values == full
    assert len(result.segments) == 1


def test_gap_is_detected_not_filled():
    svc = DemoRangeService(page_size=3, threshold=4)
    full = _values(10)
    calls = {"n": 0}

    def fetcher(tag: str):
        option = tag if "range=" in tag else None
        seg_tag, chunk = svc.serve("member", full, option)
        calls["n"] += 1
        if calls["n"] == 2:  # corrupt the second segment: jump low forward
            return "member;range=5-*", chunk
        return seg_tag, chunk

    result = RangeAssembler(fetcher).fetch("member")
    assert not result.complete
    assert any(f.kind == "gap" for f in result.faults)
    fault = next(f for f in result.faults if f.kind == "gap")
    assert "3..4" in fault.detail


def test_overlap_is_detected():
    svc = DemoRangeService(page_size=3, threshold=4)
    full = _values(10)
    calls = {"n": 0}

    def fetcher(tag: str):
        option = tag if "range=" in tag else None
        seg_tag, chunk = svc.serve("member", full, option)
        calls["n"] += 1
        if calls["n"] == 2:
            return "member;range=1-*", chunk  # overlaps indices 1..2
        return seg_tag, chunk

    result = RangeAssembler(fetcher).fetch("member")
    assert any(f.kind == "overlap" for f in result.faults)


def test_stall_empty_open_segment_does_not_loop_forever():
    svc = DemoRangeService(page_size=3, threshold=4)
    full = _values(10)
    calls = {"n": 0}

    def fetcher(tag: str):
        option = tag if "range=" in tag else None
        seg_tag, chunk = svc.serve("member", full, option)
        calls["n"] += 1
        if calls["n"] == 2:
            return "member;range=3-*", []  # boundary cannot advance
        return seg_tag, chunk

    result = RangeAssembler(fetcher).fetch("member")
    assert any(f.kind == "stall" for f in result.faults)
    assert calls["n"] == 2  # stopped immediately, no hot loop


def test_terminal_segment_marks_complete():
    svc = DemoRangeService(page_size=3, threshold=4)
    full = _values(5)  # above threshold -> 3 + 2, concrete final bound
    result = RangeAssembler(
        lambda tag: svc.serve("member", full, tag if "range=" in tag else None)
    ).fetch("member")
    assert result.complete
    assert result.segments[-1].response_tag.endswith("3-4")


def test_missing_attribute():
    result = RangeAssembler(lambda _tag: None).fetch("member")
    assert not result.complete and result.reason == "attribute absent"
