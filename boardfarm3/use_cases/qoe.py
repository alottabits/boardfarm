"""QoE use cases.

Provides BDD-friendly wrappers around :class:`~boardfarm3.templates.qoe_client.QoEClient`
device methods.  Test steps and scenarios depend only on this module — they never call
Playwright, Chromium, or socket APIs directly.

**Device selection:**

- :func:`get_qoe_client` — returns a single :class:`~boardfarm3.templates.qoe_client.QoEClient`
  by name (multi-client) or automatically when only one is present (single-client).

**Measurement helpers** (thin wrappers that invoke device methods):

- :func:`measure_productivity` — page-load TTFB and load-time measurement.
- :func:`measure_streaming` — HLS video startup time and rebuffer ratio.
- :func:`measure_conferencing` — WebRTC RTT, jitter, packet-loss, and MOS.

**SLO assertion helpers** (assert threshold — raise ``AssertionError`` on violation):

- :func:`assert_productivity_slo` — TTFB + load time within SLO bounds.
- :func:`assert_streaming_slo` — startup time + rebuffer ratio within SLO bounds.
- :func:`assert_conferencing_slo` — MOS score above minimum threshold.
- :func:`assert_request_allowed` — verify a measurement succeeded (not blocked).
- :func:`assert_request_blocked` — verify a measurement was blocked (``success=False``).
- :func:`assert_connection_allowed` — verify TCP connection to a host:port succeeds.
- :func:`assert_connection_blocked` — verify TCP connection to a host:port is blocked.

**Design:**

SLO assertion functions never return a value — they raise :exc:`AssertionError` with a
descriptive message on failure.  Scenario steps catch :exc:`AssertionError` automatically
via pytest.  Measurement helpers return :class:`~boardfarm3.lib.qoe.QoEResult` directly
so that integration tests can make custom assertions.

See: ``docs/WAN_Edge_Appliance_testing.md §3.4`` and
``docs/QoE_Client_Implementation_Plan.md §5``
"""

from __future__ import annotations

from boardfarm3.exceptions import DeviceNotFound
from boardfarm3.lib.device_manager import get_device_manager
from boardfarm3.lib.qoe import MeasurementSpec, QoEResult, spec_from_dict
from boardfarm3.templates.qoe_client import QoEClient


# ---------------------------------------------------------------------------
# Device selection
# ---------------------------------------------------------------------------


def get_qoe_client(name: str | None = None) -> QoEClient:
    """Return a :class:`~boardfarm3.templates.qoe_client.QoEClient` device.

    Supports single-client (omit *name*) and multi-client (specify *name*) topologies.

    .. hint:: This Use Case implements statements from the test suite such as:

        - ``Given the LAN client is connected through the WAN edge``
        - ``When the LAN client measures connectivity``

    :param name: Device name (e.g. ``"lan_client"``).  If ``None`` and exactly one
        QoEClient exists, return it.  If ``None`` and multiple exist,
        raise :exc:`ValueError` asking the caller to specify a name.
    :return: Selected :class:`~boardfarm3.templates.qoe_client.QoEClient` instance.
    :raises DeviceNotFound: if no QoEClient devices are registered.
    :raises DeviceNotFound: if *name* is specified but does not match any device.
    :raises ValueError: if *name* is ``None`` and more than one QoEClient exists.
    """
    devs = get_device_manager().get_devices_by_type(
        QoEClient,  # type: ignore[type-abstract]
    )
    if not devs:
        raise DeviceNotFound("No QoEClient devices available in device manager")

    if name is not None:
        if name not in devs:
            available = list(devs)
            raise DeviceNotFound(
                f"QoEClient {name!r} not found. Available: {available}"
            )
        return devs[name]

    if len(devs) > 1:
        raise ValueError(
            f"Multiple QoEClient devices found ({list(devs)}). "
            "Specify name= to select one (e.g. get_qoe_client('lan_client'))."
        )
    return next(iter(devs.values()))


# ---------------------------------------------------------------------------
# Measurement helpers (thin wrappers — return QoEResult for custom assertions)
# ---------------------------------------------------------------------------


def measure(
    client: QoEClient,
    url: str,
    spec: MeasurementSpec | dict,
) -> QoEResult:
    """Perform a QoE measurement using a :class:`~boardfarm3.lib.qoe.MeasurementSpec`.

    This is the general-purpose entry point.  The spec describes which tool
    and completion criteria to use; the client dispatches accordingly.

    .. hint:: This Use Case implements statements from the test suite such as:

        - ``When the remote worker loads the productivity page through the appliance``
        - ``When the LAN client measures HTTP timing for "<url>"``

    :param client: Target QoEClient device.
    :param url: Target URL or endpoint.
    :param spec: :class:`~boardfarm3.lib.qoe.MeasurementSpec` or dict
        (auto-converted via :func:`~boardfarm3.lib.qoe.spec_from_dict`).
    :return: :class:`~boardfarm3.lib.qoe.QoEResult`.
    """
    if isinstance(spec, dict):
        spec = spec_from_dict(spec)
    return client.measure(url, spec)


def measure_productivity(
    client: QoEClient,
    url: str,
    *,
    spec: MeasurementSpec | dict | None = None,
    scenario: str = "page_load",
    wait_until: str = "networkidle",
    timeout_ms: int = 30000,
) -> QoEResult:
    """Measure TTFB and page-load time for a productivity URL via *client*.

    When *spec* is provided, it takes precedence over the individual keyword
    arguments.  When *spec* is ``None``, the kwargs are used to construct a
    default browser spec (backward compatible).

    .. hint:: This Use Case implements statements from the test suite such as:

        - ``When the LAN client measures productivity for "<url>"``
        - ``When the LAN client loads the productivity web page``
        - ``Measure Productivity    ${client}    ${url}``

    :param client: Target QoEClient device.
    :param url: Target URL (e.g. ``"http://productivity.internal/"``).
    :param spec: Optional :class:`~boardfarm3.lib.qoe.MeasurementSpec` or dict.
    :param scenario: Scenario label for logging (default ``"page_load"``).
    :param wait_until: Browser completion event (default ``"networkidle"``).
        Ignored when *spec* is provided.
    :param timeout_ms: Navigation timeout (ms, default 30000).
        Ignored when *spec* is provided.
    :return: :class:`~boardfarm3.lib.qoe.QoEResult` with productivity fields populated.
    """
    if isinstance(spec, dict):
        spec = spec_from_dict(spec)
    if spec is not None:
        return client.measure(url, spec)
    return client.measure_productivity(
        url, scenario=scenario, wait_until=wait_until, timeout_ms=timeout_ms,
    )


def measure_http_timing(
    client: QoEClient,
    url: str,
    *,
    spec: MeasurementSpec | dict | None = None,
    timeout_s: float = 30.0,
) -> QoEResult:
    """Lightweight HTTP timing measurement (no browser).

    .. hint:: This Use Case implements statements from the test suite such as:

        - ``When the LAN client probes HTTP timing for "<url>"``

    :param client: Target QoEClient device.
    :param url: Target URL.
    :param spec: Optional :class:`~boardfarm3.lib.qoe.MeasurementSpec` or dict.
    :param timeout_s: Request timeout (seconds, default 30.0).
        Ignored when *spec* is provided.
    :return: :class:`~boardfarm3.lib.qoe.QoEResult` with timing fields populated.
    """
    if isinstance(spec, dict):
        spec = spec_from_dict(spec)
    return client.measure_http_timing(url, spec=spec, timeout_s=timeout_s)


def measure_streaming(
    client: QoEClient,
    stream_url: str,
    *,
    spec: MeasurementSpec | dict | None = None,
    duration_s: int = 30,
) -> QoEResult:
    """Measure video startup time and rebuffer ratio for an HLS stream via *client*.

    .. hint:: This Use Case implements statements from the test suite such as:

        - ``When the LAN client streams video from "<stream_url>"``
        - ``When the LAN client plays the HLS stream for <duration> seconds``
        - ``Measure Streaming    ${client}    ${stream_url}``

    :param client: Target QoEClient device.
    :param stream_url: HLS manifest URL
        (e.g. ``"http://streaming.internal/live/stream.m3u8"``).
    :param duration_s: Simulated playback duration in seconds (default 30).
    :return: :class:`~boardfarm3.lib.qoe.QoEResult` with streaming fields populated.
    """
    if isinstance(spec, dict):
        spec = spec_from_dict(spec)
    if spec is not None:
        return client.measure(stream_url, spec)
    return client.measure_streaming(stream_url, duration_s=duration_s)


def measure_conferencing(
    client: QoEClient,
    session_url: str,
    *,
    spec: MeasurementSpec | dict | None = None,
    duration_s: int = 60,
) -> QoEResult:
    """Measure WebRTC RTT, jitter, packet-loss, and MOS via *client*.

    .. hint:: This Use Case implements statements from the test suite such as:

        - ``When the LAN client joins a conferencing session at "<session_url>"``
        - ``When the LAN client establishes a WebRTC session for <duration> seconds``
        - ``Measure Conferencing    ${client}    ${session_url}``

    :param client: Target QoEClient device.
    :param session_url: WebRTC signaling endpoint URL
        (e.g. ``"ws://conf-server.internal:8080/session"``).
    :param duration_s: Session duration for stat accumulation (default 60).
    :return: :class:`~boardfarm3.lib.qoe.QoEResult` with conferencing fields populated.
    """
    if isinstance(spec, dict):
        spec = spec_from_dict(spec)
    if spec is not None:
        return client.measure(session_url, spec)
    return client.measure_conferencing(session_url, duration_s=duration_s)


# ---------------------------------------------------------------------------
# SLO assertion helpers — raise AssertionError on violation
# ---------------------------------------------------------------------------


def assert_productivity_slo(
    result: QoEResult,
    *,
    max_ttfb_ms: float | None = None,
    max_load_time_ms: float | None = None,
    label: str = "",
) -> None:
    """Assert that a productivity measurement meets its SLO thresholds.

    At least one of *max_ttfb_ms* or *max_load_time_ms* must be provided.
    A ``None`` metric in *result* is treated as a violation of any bound set on it
    (the measurement failed to produce the value).

    .. hint:: This Use Case implements statements from the test suite such as:

        - ``Then the productivity SLO is met with TTFB below <ms> ms``
        - ``Then the page load time is within the SLO for "<condition>"``
        - ``Assert Productivity SLO    ${result}    max_ttfb_ms=200``

    :param result: :class:`~boardfarm3.lib.qoe.QoEResult` from :func:`measure_productivity`.
    :param max_ttfb_ms: Maximum acceptable TTFB (ms).  ``None`` = do not check.
    :param max_load_time_ms: Maximum acceptable page-load time (ms).  ``None`` = do not check.
    :param label: Optional label for error messages (e.g. ``"cable_typical"``).
    :raises AssertionError: if ``result.success`` is ``False`` or any threshold is exceeded.
    """
    prefix = f"[{label}] " if label else ""

    assert result.success, (
        f"{prefix}Productivity measurement failed (success=False). "
        "The request was blocked or returned an error."
    )

    if max_ttfb_ms is not None:
        assert result.ttfb_ms is not None, (
            f"{prefix}TTFB not measured (result.ttfb_ms is None)"
        )
        assert result.ttfb_ms <= max_ttfb_ms, (
            f"{prefix}TTFB SLO violation: "
            f"{result.ttfb_ms:.1f} ms > max {max_ttfb_ms:.1f} ms"
        )

    if max_load_time_ms is not None:
        assert result.load_time_ms is not None, (
            f"{prefix}Load time not measured (result.load_time_ms is None)"
        )
        assert result.load_time_ms <= max_load_time_ms, (
            f"{prefix}Page load time SLO violation: "
            f"{result.load_time_ms:.1f} ms > max {max_load_time_ms:.1f} ms"
        )


def assert_streaming_slo(
    result: QoEResult,
    *,
    max_startup_time_ms: float | None = None,
    max_rebuffer_ratio: float | None = None,
    label: str = "",
) -> None:
    """Assert that a streaming measurement meets its SLO thresholds.

    .. hint:: This Use Case implements statements from the test suite such as:

        - ``Then the streaming SLO is met: startup below <ms> ms``
        - ``Then the video rebuffer ratio is within acceptable bounds for "<condition>"``
        - ``Assert Streaming SLO    ${result}    max_startup_time_ms=2000``

    :param result: :class:`~boardfarm3.lib.qoe.QoEResult` from :func:`measure_streaming`.
    :param max_startup_time_ms: Maximum acceptable startup time (ms).  ``None`` = skip.
    :param max_rebuffer_ratio: Maximum acceptable rebuffer ratio (0.0–1.0).  ``None`` = skip.
    :param label: Optional label for error messages.
    :raises AssertionError: if ``result.success`` is ``False`` or any threshold is exceeded.
    """
    prefix = f"[{label}] " if label else ""

    assert result.success, (
        f"{prefix}Streaming measurement failed (success=False). "
        "The manifest or first segment was unreachable."
    )

    if max_startup_time_ms is not None:
        assert result.startup_time_ms is not None, (
            f"{prefix}Startup time not measured (result.startup_time_ms is None)"
        )
        assert result.startup_time_ms <= max_startup_time_ms, (
            f"{prefix}Streaming startup SLO violation: "
            f"{result.startup_time_ms:.1f} ms > max {max_startup_time_ms:.1f} ms"
        )

    if max_rebuffer_ratio is not None:
        assert result.rebuffer_ratio is not None, (
            f"{prefix}Rebuffer ratio not measured (result.rebuffer_ratio is None)"
        )
        assert result.rebuffer_ratio <= max_rebuffer_ratio, (
            f"{prefix}Rebuffer ratio SLO violation: "
            f"{result.rebuffer_ratio:.4f} > max {max_rebuffer_ratio:.4f}"
        )


def assert_conferencing_slo(
    result: QoEResult,
    *,
    min_mos: float = 3.5,
    max_latency_ms: float | None = None,
    max_jitter_ms: float | None = None,
    max_packet_loss_pct: float | None = None,
    label: str = "",
) -> None:
    """Assert that a conferencing measurement meets its SLO thresholds.

    .. hint:: This Use Case implements statements from the test suite such as:

        - ``Then the conferencing MOS score exceeds <min_mos> for "<condition>"``
        - ``Then the WebRTC session quality is acceptable under WAN impairment``
        - ``Assert Conferencing SLO    ${result}    min_mos=3.5``

    :param result: :class:`~boardfarm3.lib.qoe.QoEResult` from :func:`measure_conferencing`.
    :param min_mos: Minimum acceptable MOS score (default 3.5 — "good quality").
    :param max_latency_ms: Maximum acceptable one-way latency (ms).  ``None`` = skip.
    :param max_jitter_ms: Maximum acceptable jitter (ms).  ``None`` = skip.
    :param max_packet_loss_pct: Maximum acceptable packet-loss (%).  ``None`` = skip.
    :param label: Optional label for error messages.
    :raises AssertionError: if ``result.success`` is ``False`` or any threshold is exceeded.
    """
    prefix = f"[{label}] " if label else ""

    assert result.success, (
        f"{prefix}Conferencing measurement failed (success=False). "
        "The WebRTC session could not be established."
    )

    assert result.mos_score is not None, (
        f"{prefix}MOS not calculated (conferencing metrics unavailable)"
    )
    assert result.mos_score >= min_mos, (
        f"{prefix}MOS SLO violation: {result.mos_score:.3f} < min {min_mos:.3f}"
    )

    if max_latency_ms is not None:
        assert result.latency_ms is not None, (
            f"{prefix}Latency not measured (result.latency_ms is None)"
        )
        assert result.latency_ms <= max_latency_ms, (
            f"{prefix}Conferencing latency SLO violation: "
            f"{result.latency_ms:.1f} ms > max {max_latency_ms:.1f} ms"
        )

    if max_jitter_ms is not None:
        assert result.jitter_ms is not None, (
            f"{prefix}Jitter not measured (result.jitter_ms is None)"
        )
        assert result.jitter_ms <= max_jitter_ms, (
            f"{prefix}Conferencing jitter SLO violation: "
            f"{result.jitter_ms:.1f} ms > max {max_jitter_ms:.1f} ms"
        )

    if max_packet_loss_pct is not None:
        assert result.packet_loss_pct is not None, (
            f"{prefix}Packet loss not measured (result.packet_loss_pct is None)"
        )
        assert result.packet_loss_pct <= max_packet_loss_pct, (
            f"{prefix}Conferencing packet-loss SLO violation: "
            f"{result.packet_loss_pct:.2f}% > max {max_packet_loss_pct:.2f}%"
        )


def assert_request_allowed(result: QoEResult, *, label: str = "") -> None:
    """Assert that a QoE measurement succeeded (request was *not* blocked).

    Raises :exc:`AssertionError` when ``result.success`` is ``False``, indicating
    that the WAN Edge appliance blocked a request that should have been allowed.

    .. hint:: This Use Case implements statements from the test suite such as:

        - ``Then the request to "<url>" is allowed by the WAN edge``
        - ``Then the LAN client can access the productivity service``
        - ``Assert Request Allowed    ${result}``

    :param result: Any :class:`~boardfarm3.lib.qoe.QoEResult` from a ``measure_*`` call.
    :param label: Optional label for the assertion message.
    :raises AssertionError: if the request was blocked (``result.success == False``).
    """
    prefix = f"[{label}] " if label else ""
    assert result.success, (
        f"{prefix}Request was unexpectedly blocked "
        "(expected: allowed, got: success=False)"
    )


def assert_request_blocked(result: QoEResult, *, label: str = "") -> None:
    """Assert that a QoE measurement was blocked (``success=False``).

    Raises :exc:`AssertionError` when ``result.success`` is ``True``, indicating
    that the WAN Edge appliance allowed a request that should have been blocked
    (e.g. Application Control should have blocked an EICAR download).

    .. hint:: This Use Case implements statements from the test suite such as:

        - ``Then the EICAR download attempt is blocked by Application Control``
        - ``Then the request to the malicious URL is denied by the WAN edge``
        - ``Assert Request Blocked    ${result}``

    :param result: Any :class:`~boardfarm3.lib.qoe.QoEResult` from a ``measure_*`` call.
    :param label: Optional label for the assertion message.
    :raises AssertionError: if the request succeeded (``result.success == True``).
    """
    prefix = f"[{label}] " if label else ""
    assert not result.success, (
        f"{prefix}Request was unexpectedly allowed "
        "(expected: blocked, got: success=True)"
    )


def assert_connection_allowed(
    client: QoEClient,
    host: str,
    port: int,
    *,
    timeout_s: float = 5.0,
    label: str = "",
) -> None:
    """Assert that a TCP connection from *client* to *host*:*port* succeeds.

    .. hint:: This Use Case implements statements from the test suite such as:

        - ``Then the LAN client can reach "<host>" on port <port>``
        - ``Then the TCP connection to the application server is allowed``
        - ``Assert Connection Allowed    ${client}    ${host}    ${port}``

    :param client: Source QoEClient device.
    :param host: Target hostname or IP.
    :param port: Target TCP port.
    :param timeout_s: Connection timeout (default 5.0 s).
    :param label: Optional label for the assertion message.
    :raises AssertionError: if the connection was blocked or refused.
    """
    prefix = f"[{label}] " if label else ""
    connected = client.attempt_outbound_connection(host, port, timeout_s=timeout_s)
    assert connected, (
        f"{prefix}TCP connection to {host}:{port} was unexpectedly blocked "
        "(expected: allowed)"
    )


def assert_connection_blocked(
    client: QoEClient,
    host: str,
    port: int,
    *,
    timeout_s: float = 5.0,
    label: str = "",
) -> None:
    """Assert that a TCP connection from *client* to *host*:*port* is blocked.

    .. hint:: This Use Case implements statements from the test suite such as:

        - ``Then the TCP connection to the C2 server on port <port> is blocked``
        - ``Then the LAN client cannot reach the malicious host``
        - ``Assert Connection Blocked    ${client}    ${host}    ${port}``

    :param client: Source QoEClient device.
    :param host: Target hostname or IP.
    :param port: Target TCP port.
    :param timeout_s: Connection timeout (default 5.0 s).
    :param label: Optional label for the assertion message.
    :raises AssertionError: if the connection succeeds (should have been blocked).
    """
    prefix = f"[{label}] " if label else ""
    connected = client.attempt_outbound_connection(host, port, timeout_s=timeout_s)
    assert not connected, (
        f"{prefix}TCP connection to {host}:{port} was unexpectedly allowed "
        "(expected: blocked)"
    )
