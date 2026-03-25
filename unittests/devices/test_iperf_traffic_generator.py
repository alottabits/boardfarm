"""Unit tests for IperfTrafficGenerator._parse_iperf3_json.

Covers single-document, multi-document (concatenated JSON from --forceflush),
no-JSON, and malformed input.
"""

from __future__ import annotations

import json

import pytest

from boardfarm3.devices.iperf_traffic_generator import IperfTrafficGenerator
from boardfarm3.templates.traffic_generator import TrafficResult

_parse = IperfTrafficGenerator._parse_iperf3_json

# -- Sample iPerf3 JSON fragments --

_COMPLETE_UDP_RESULT = {
    "start": {"test_start": {"protocol": "UDP"}},
    "intervals": [],
    "end": {
        "sum_sent": {"bits_per_second": 85_000_000},
        "sum_received": {"bits_per_second": 84_500_000},
        "sum": {
            "bits_per_second": 84_500_000,
            "jitter_ms": 0.42,
            "lost_percent": 0.12,
        },
    },
}

_INTERVAL_ONLY = {
    "start": {"test_start": {"protocol": "UDP"}},
    "intervals": [{"sum": {"bits_per_second": 80_000_000}}],
}


class TestParseSingleDocument:
    """Single, clean JSON document — normal completion."""

    def test_parses_sent_and_received(self):
        raw = json.dumps(_COMPLETE_UDP_RESULT)
        result = _parse(raw, dscp=0)
        assert result.sent_mbps == pytest.approx(85.0)
        assert result.received_mbps == pytest.approx(84.5)

    def test_parses_loss_and_jitter(self):
        raw = json.dumps(_COMPLETE_UDP_RESULT)
        result = _parse(raw, dscp=0)
        assert result.loss_percent == pytest.approx(0.12)
        assert result.jitter_ms == pytest.approx(0.42)

    def test_preserves_dscp(self):
        raw = json.dumps(_COMPLETE_UDP_RESULT)
        result = _parse(raw, dscp=46)
        assert result.dscp_marking == 46


class TestParseMultiDocument:
    """Multiple concatenated JSON documents — killed mid-flow with --forceflush."""

    def test_selects_last_document_with_end_block(self):
        interval_json = json.dumps(_INTERVAL_ONLY)
        final_json = json.dumps(_COMPLETE_UDP_RESULT)
        raw = interval_json + "\n" + final_json
        result = _parse(raw, dscp=0)
        assert result.sent_mbps == pytest.approx(85.0)
        assert result.loss_percent == pytest.approx(0.12)

    def test_three_documents_picks_last_with_end(self):
        frag1 = json.dumps(_INTERVAL_ONLY)
        frag2 = json.dumps(_INTERVAL_ONLY)
        frag3 = json.dumps(_COMPLETE_UDP_RESULT)
        raw = frag1 + frag2 + frag3
        result = _parse(raw, dscp=0)
        assert result.sent_mbps == pytest.approx(85.0)

    def test_no_end_block_falls_back_to_last_document(self):
        raw = json.dumps(_INTERVAL_ONLY) + json.dumps(_INTERVAL_ONLY)
        result = _parse(raw, dscp=0)
        assert isinstance(result, TrafficResult)
        assert result.sent_mbps == 0.0


class TestParseEdgeCases:
    """Malformed input, missing data, empty output."""

    def test_no_json_returns_zero_result(self):
        result = _parse("no json here at all", dscp=0)
        assert result.sent_mbps == 0.0
        assert result.received_mbps == 0.0

    def test_empty_string_returns_zero_result(self):
        result = _parse("", dscp=0)
        assert result.sent_mbps == 0.0

    def test_empty_braces_returns_zero_result(self):
        result = _parse("{}", dscp=0)
        assert result.sent_mbps == 0.0
        assert result.loss_percent == 0.0

    def test_json_with_leading_garbage(self):
        raw = "some prompt output\n" + json.dumps(_COMPLETE_UDP_RESULT)
        result = _parse(raw, dscp=0)
        assert result.sent_mbps == pytest.approx(85.0)

    def test_json_with_trailing_garbage(self):
        raw = json.dumps(_COMPLETE_UDP_RESULT) + "\n[1]+  Exit 1  nohup iperf3 ..."
        result = _parse(raw, dscp=0)
        assert result.sent_mbps == pytest.approx(85.0)
