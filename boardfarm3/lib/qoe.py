"""QoE (Quality of Experience) library — shared schema and MOS calculation.

This module is the **sole source of truth** for:

- :class:`QoEResult` — the measurement result object returned by every
  :class:`~boardfarm3.templates.qoe_client.QoEClient` method and consumed by
  :mod:`~boardfarm3.use_cases.qoe` SLO assertions.
- :func:`calculate_mos` — MOS R-Factor calculation using the ITU-T G.107 E-model
  simplified for IP networks. Called by the use-case layer, never by step definitions.

**Architecture placement:**

Both the template layer and the use-case layer import :class:`QoEResult` from here::

    boardfarm3/lib/qoe.py                     ← QoEResult + calculate_mos()
    boardfarm3/templates/qoe_client.py        ← QoEClient ABC (imports QoEResult from lib)
    boardfarm3/devices/playwright_qoe_client.py  ← concrete implementation
    boardfarm3/use_cases/qoe.py               ← SLO assertions (imports QoEResult from lib)

See: ``docs/QoE_Client_Implementation_Plan.md §3.2`` and
``docs/WAN_Edge_Appliance_testing.md §3.4``
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class QoEResult:
    """Result of a single QoE measurement.

    All fields are ``None`` when not applicable to the measurement type — field
    presence does not imply the measurement occurred; always check for ``None``
    before asserting a threshold.

    ``success`` defaults to ``True``; the device class sets it to ``False`` when the
    underlying request was blocked or failed (e.g. HTTP 4xx/5xx, network error, or an
    EICAR download intercepted by Application Control).

    **Productivity fields** (populated by :meth:`~boardfarm3.templates.qoe_client.QoEClient.measure_productivity`):

    - :attr:`ttfb_ms` — Time to First Byte (ms).
    - :attr:`load_time_ms` — Full page load time (ms).

    **Streaming fields** (populated by :meth:`~boardfarm3.templates.qoe_client.QoEClient.measure_streaming`):

    - :attr:`startup_time_ms` — Video startup latency (ms).
    - :attr:`rebuffer_ratio` — Fraction of session spent buffering (0.0 – 1.0).

    **Conferencing fields** (populated by :meth:`~boardfarm3.templates.qoe_client.QoEClient.measure_conferencing`):

    - :attr:`latency_ms` — RTT from ``RTCPeerConnection.getStats()``.
    - :attr:`jitter_ms` — Jitter from ``RTCPeerConnection.getStats()``.
    - :attr:`packet_loss_pct` — Packet loss from ``RTCPeerConnection.getStats()``.
    - :attr:`mos_score` — Mean Opinion Score (1.0–5.0), calculated via :func:`calculate_mos`.

    **Transport metadata** (Phase 3.5+):

    - :attr:`protocol` — HTTP version negotiated (``'http/1.1'``, ``'h2'``, ``'h3'``).
      ``None`` in Phase 1–3 (plain HTTP).

    **Request outcome**:

    - :attr:`success` — ``False`` when the request was blocked or failed.
    """

    # --- Productivity / page-load metrics ---
    ttfb_ms: float | None = None
    """Time to First Byte (ms): ``responseStart − requestStart`` (Navigation Timing)."""

    load_time_ms: float | None = None
    """Full page load time (ms): ``loadEventEnd − navigationStart``."""

    # --- Streaming metrics ---
    startup_time_ms: float | None = None
    """Video startup latency (ms): time from ``play()`` to ``'playing'`` event."""

    rebuffer_ratio: float | None = None
    """Fraction of session spent buffering (0.0 = no rebuffering, 1.0 = all buffering)."""

    # --- Conferencing metrics (WebRTC getStats()) ---
    latency_ms: float | None = None
    """Round-trip time (ms) from ``RTCPeerConnection.getStats()``."""

    jitter_ms: float | None = None
    """Jitter (ms) from ``RTCPeerConnection.getStats()``."""

    packet_loss_pct: float | None = None
    """Packet loss percentage from ``RTCPeerConnection.getStats()``."""

    mos_score: float | None = None
    """Mean Opinion Score (1.0–5.0) calculated by :func:`calculate_mos` using ITU-T G.107 E-model."""

    # --- Transport metadata (Phase 3.5+) ---
    protocol: str | None = None
    """HTTP version negotiated: ``'http/1.1'``, ``'h2'``, ``'h3'``.
    Populated from Navigation Timing ``nextHopProtocol``. ``None`` in Phase 1–3."""

    # --- Request outcome ---
    success: bool = True
    """``False`` when the underlying request was blocked or failed.
    Used by security use-case assertions (e.g. EICAR download blocked, C2 callback blocked)."""


# ---------------------------------------------------------------------------
# Measurement specification — portable description of HOW to measure
# ---------------------------------------------------------------------------


@dataclass
class MeasurementSpec:
    """Describes how a QoE measurement should be conducted.

    Separates two orthogonal concerns:

    - **tool** — which measurement engine to use.
    - **completion** — what event signals the measurement is complete.

    The same tool + completion combination can measure different things depending
    on the target URL and which :class:`QoEResult` fields are asserted.  This
    follows the :class:`~boardfarm3.lib.traffic_control.ImpairmentProfile` pattern:
    a single portable dataclass that the template accepts and the concrete device
    implementation translates to engine-specific operations.

    **Tool × Completion matrix:**

    ================  ===============================================
    Tool              Valid completion events
    ================  ===============================================
    ``browser``       ``networkidle``, ``load``, ``domcontentloaded``
    ``http_client``   ``response``, ``duration``
    ``webrtc``        ``duration``
    ``tcp_probe``     ``connect``
    ================  ===============================================
    """

    tool: str = "browser"
    """Measurement engine:

    - ``'browser'`` — Playwright / Chromium (full page navigation, JS execution).
    - ``'http_client'`` — urllib (lightweight HTTP request / response timing).
    - ``'webrtc'`` — WebRTC peer-connection session via Playwright.
    - ``'tcp_probe'`` — TCP socket connection attempt.
    """

    completion: str = "networkidle"
    """When the measurement is considered complete:

    - ``'networkidle'`` — no network connections for 500 ms (browser).
    - ``'load'`` — browser ``load`` event (``loadEventEnd`` in Navigation Timing).
    - ``'domcontentloaded'`` — DOM content loaded event (browser).
    - ``'response'`` — HTTP response fully received (http_client).
    - ``'duration'`` — run for :attr:`duration_s` seconds (webrtc, streaming).
    - ``'connect'`` — TCP handshake completed or refused (tcp_probe).
    """

    timeout_ms: int = 30000
    """Maximum time to wait for the completion event (milliseconds)."""

    duration_s: int | None = None
    """Session length for duration-based completion (seconds).

    Required when ``completion='duration'``.  Ignored for other completion types.
    """


# --- Validation ---

VALID_TOOLS: set[str] = {"browser", "http_client", "webrtc", "tcp_probe"}

VALID_COMPLETIONS: dict[str, set[str]] = {
    "browser": {"networkidle", "load", "domcontentloaded"},
    "http_client": {"response", "duration"},
    "webrtc": {"duration"},
    "tcp_probe": {"connect"},
}


def validate_spec(spec: MeasurementSpec) -> None:
    """Raise :exc:`ValueError` if *spec* has an invalid tool + completion combination.

    Also checks that ``duration_s`` is provided when ``completion='duration'``.
    """
    if spec.tool not in VALID_TOOLS:
        raise ValueError(
            f"Unknown measurement tool {spec.tool!r}. "
            f"Expected one of: {sorted(VALID_TOOLS)}"
        )
    valid = VALID_COMPLETIONS[spec.tool]
    if spec.completion not in valid:
        raise ValueError(
            f"Completion {spec.completion!r} is not valid for tool {spec.tool!r}. "
            f"Expected one of: {sorted(valid)}"
        )
    if spec.completion == "duration" and spec.duration_s is None:
        raise ValueError(
            "duration_s is required when completion='duration'"
        )


def spec_from_dict(data: dict) -> MeasurementSpec:
    """Parse a plain dict to a :class:`MeasurementSpec`.

    Accepts any subset of :class:`MeasurementSpec` fields.  Unknown keys are
    silently ignored for forward compatibility (e.g., env-config may carry
    metadata fields).  Validates the resulting spec.

    :param data: Dict from env JSON preset or test code.
    :return: Validated :class:`MeasurementSpec`.
    :raises ValueError: if the tool + completion combination is invalid.
    """
    import dataclasses as _dc

    valid_keys = {f.name for f in _dc.fields(MeasurementSpec)}
    filtered = {k: v for k, v in data.items() if k in valid_keys}
    spec = MeasurementSpec(**filtered)
    validate_spec(spec)
    return spec


# ---------------------------------------------------------------------------
# MOS calculation — ITU-T G.107 E-model (simplified for IP networks)
# ---------------------------------------------------------------------------


def calculate_mos(
    latency_ms: float,
    jitter_ms: float,
    loss_percent: float,
    *,
    ro: float = 93.2,
    ie: float = 0.0,
    bpl: float = 25.1,
    advantage_factor: float = 0.0,
) -> float:
    """Estimate the Mean Opinion Score (MOS) using the ITU-T G.107 E-model.

    The E-model computes an R-Factor from impairment contributions and converts it
    to a MOS score in the range **1.0–4.5**.

    **R-Factor formula:**

    ``R = Ro - Is - Id - Ie_eff + A``

    where:

    - ``Ro`` — basic signal-to-noise ratio (default 93.2 for G.711 baseline).
    - ``Is`` — simultaneous impairment (codec distortion; default 0.0).
    - ``Id`` — delay impairment (one-way latency + jitter contributions).
    - ``Ie_eff`` — effective equipment impairment (codec quality degraded by packet loss).
    - ``A`` — advantage factor for mobility / convenience (default 0.0 for wired links).

    **Delay impairment** (``Id``):

    Uses the standard E-model delay penalty::

        h = latency_effective - 177.3   (where latency_effective = latency_ms + jitter_ms/2)
        Id = 0.024 * latency_effective + 0.11 * max(0, h)

    **Equipment impairment** (``Ie_eff``):

    Degraded by packet loss using the Packet Loss Robustness factor ``Bpl``::

        Ie_eff = Ie + (95 - Ie) * loss_percent / (loss_percent + Bpl)

    **R → MOS conversion:**

    The standard ITU-T formula clamps R to [0, 100] then applies the cubic mapping::

        MOS = 1 + 0.035 * R + R * (R - 60) * (100 - R) * 7e-6

    Clamped to [1.0, 4.5].

    :param latency_ms: One-way latency in milliseconds (e.g. RTT / 2 from WebRTC getStats()).
    :param jitter_ms: Jitter in milliseconds from WebRTC getStats().
    :param loss_percent: Packet loss percentage (0.0–100.0).
    :param ro: Basic signal-to-noise ratio (default 93.2).
    :param ie: Baseline equipment impairment for the codec (default 0.0 for ideal codec).
    :param bpl: Packet-loss robustness factor (default 25.1, appropriate for Opus/G.711).
    :param advantage_factor: Advantage factor for mobility scenarios (default 0.0).
    :return: Estimated MOS score, clamped to [1.0, 4.5].
    """
    # Effective one-way latency includes half of jitter (worst-case playout buffer)
    latency_eff = latency_ms + jitter_ms / 2.0

    # Delay impairment (Id) — ITU-T G.107 §B.2
    h = latency_eff - 177.3
    id_factor = 0.024 * latency_eff + 0.11 * (h if h > 0 else 0.0)

    # Effective equipment impairment (Ie_eff) — degraded by packet loss
    ppl = max(0.0, loss_percent)
    ie_eff = ie + (95.0 - ie) * ppl / (ppl + bpl) if ppl > 0 else ie

    # R-Factor
    r_factor = ro - id_factor - ie_eff + advantage_factor
    r_factor = max(0.0, min(100.0, r_factor))

    # R → MOS cubic mapping (ITU-T G.107 §B.4)
    if r_factor <= 0:
        return 1.0
    if r_factor >= 100:
        return 4.5
    mos = 1.0 + 0.035 * r_factor + r_factor * (r_factor - 60.0) * (100.0 - r_factor) * 7e-6
    return round(max(1.0, min(4.5, mos)), 3)
