"""The contract between the Gateway and the agent: AgentResult is a list of per-part segments plus one handoff."""
from dataclasses import asdict

from app.agent import AgentResult, Segment


def test_a_result_holds_one_segment_per_answered_part_in_written_order():
    result = AgentResult(segments=[
        Segment(0, "template", template_id=1, render_values={"order_status": "Shipped"}),
        Segment(1, "text", text="Your return window is {days_left} days.", template_id=2,
                render_values={"days_left": "5"}, cited=["POL-RET-001 §2@2.1"]),
    ], handoff_reason="BKD", priority="P3")
    assert [s.part_index for s in result.segments] == [0, 1]
    assert result.segments[1].template_id == 2          # the fallback if the text fails validation


def test_cited_is_derived_from_the_segments_without_duplicates():
    result = AgentResult(segments=[
        Segment(0, "text", text="a", cited=["POL-RET-001 §2@2.1", "POL-EXC-001 §1@1.0"]),
        Segment(1, "text", text="b", cited=["POL-RET-001 §2@2.1"]),
    ])
    assert result.cited == ["POL-RET-001 §2@2.1", "POL-EXC-001 §1@1.0"]


def test_an_empty_result_has_no_segments_and_no_handoff():
    result = AgentResult()
    assert (result.segments, result.handoff_reason, result.priority, result.cited) == ([], None, None, [])


def test_the_gateway_can_turn_the_result_into_json():
    result = AgentResult(segments=[Segment(0, "template", template_id=14)], handoff_reason="SCOPE", priority="P4")
    assert asdict(result) == {"segments": [{"part_index": 0, "kind": "template", "template_id": 14, "text": None,
                                            "render_values": {}, "cited": []}],
                              "handoff_reason": "SCOPE", "priority": "P4",
                              "block_session_data": False, "handoff_summary": None, "telemetry": {}, "memory": {}}
