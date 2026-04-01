"""Boardfarm QoEClient device template.

Defines the abstract interface for Quality-of-Experience (QoE) measurement clients.
Use cases depend only on this interface — concrete implementations (Playwright,
hardware appliances) are interchangeable.

**Four-pillar measurement contract:**

- :meth:`measure_productivity` — page-load TTFB and load-time metrics.
- :meth:`measure_streaming` — video startup time and rebuffer ratio.
- :meth:`measure_conferencing` — WebRTC RTT, jitter, packet-loss, and MOS.
- :meth:`attempt_outbound_connection` — TCP reachability probe (security tests).

**Transport metadata (Phase 3.5+):**

:meth:`measure_productivity` and :meth:`measure_streaming` populate
:attr:`~boardfarm3.lib.qoe.QoEResult.protocol` with the HTTP version negotiated
(``'h2'``, ``'h3'``, ``'http/1.1'``).  In Phase 1–3, ``protocol`` is ``None``.

**Security integration:**

:meth:`attempt_outbound_connection` is used by security use-case assertions to verify
that a WAN Edge appliance's policy correctly blocks (or allows) outbound TCP connections.
The method returns ``True`` if the TCP handshake completes and ``False`` if the connection
is refused, timed out, or intercepted.

See: ``docs/QoE_Client_Implementation_Plan.md`` and
``docs/WAN_Edge_Appliance_testing.md §3.3``
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from boardfarm3.lib.qoe import MeasurementSpec, QoEResult


class QoEClient(ABC):
    """Abstract interface for QoE measurement devices.

    Implementations (e.g. :class:`~boardfarm3.devices.playwright_qoe_client.PlaywrightQoEClient`)
    SSH into a container running Playwright + Chromium and return
    :class:`~boardfarm3.lib.qoe.QoEResult` objects.

    Use cases interact *only* with this interface.  Scenario authors choose a device
    name; the test framework instantiates the correct concrete class.

    **Multi-device support:**

    When the testbed has multiple LAN clients (e.g. ``lan_client_1``, ``lan_client_2``),
    :func:`~boardfarm3.use_cases.qoe.get_qoe_client` accepts an optional ``name``
    parameter to select the right one.

    **Failure semantics:**

    All ``measure_*`` methods return a :class:`~boardfarm3.lib.qoe.QoEResult` even when
    the operation fails — ``success=False`` is set and all metric fields are ``None``.
    They **never raise** for expected network failures (blocked connections, HTTP errors).
    They **do raise** for configuration errors (unknown URL scheme, missing credentials).
    """

    @property
    @abstractmethod
    def ip_address(self) -> str:
        """LAN-side IP address of this client on the simulated network.

        Used by security use-case assertions to identify the source host for
        SIEM / firewall log correlation.  Returned from the device's
        ``simulated_ip`` inventory config key.
        """
        raise NotImplementedError

    @abstractmethod
    def measure(
        self,
        url: str,
        spec: "MeasurementSpec",
    ) -> "QoEResult":
        """Perform a QoE measurement using the specified tool and completion criteria.

        This is the core measurement method.  Concrete implementations dispatch
        on ``spec.tool`` to select the measurement engine (browser, http_client,
        webrtc, tcp_probe) and use ``spec.completion`` to determine when the
        measurement is done.

        The named convenience methods (:meth:`measure_productivity`,
        :meth:`measure_streaming`, etc.) construct a default
        :class:`~boardfarm3.lib.qoe.MeasurementSpec` and delegate here.

        :param url: Target URL or endpoint.
        :param spec: :class:`~boardfarm3.lib.qoe.MeasurementSpec` describing the
            measurement tool, completion event, timeout, and optional duration.
        :return: :class:`~boardfarm3.lib.qoe.QoEResult` with fields populated
            according to the measurement type.
        """
        raise NotImplementedError

    def measure_http_timing(
        self,
        url: str,
        *,
        spec: "MeasurementSpec | None" = None,
        timeout_s: float = 30.0,
    ) -> "QoEResult":
        """Lightweight HTTP timing measurement (no browser).

        Measures TTFB and total response time for a single HTTP request using
        ``urllib``.  No Playwright / Chromium overhead — suitable for
        page-load SLO probes under impaired WAN conditions.

        Populated fields in the returned :class:`~boardfarm3.lib.qoe.QoEResult`:

        - :attr:`~boardfarm3.lib.qoe.QoEResult.ttfb_ms`
        - :attr:`~boardfarm3.lib.qoe.QoEResult.load_time_ms`
        - :attr:`~boardfarm3.lib.qoe.QoEResult.success`

        :param url: Target URL.
        :param spec: Optional :class:`~boardfarm3.lib.qoe.MeasurementSpec`.
            When ``None``, a default spec with ``tool='http_client'``,
            ``completion='response'`` is constructed.
        :param timeout_s: Request timeout (seconds, default 30.0).  Ignored
            when *spec* is provided (uses ``spec.timeout_ms``).
        :return: :class:`~boardfarm3.lib.qoe.QoEResult` with timing fields.
        """
        from boardfarm3.lib.qoe import MeasurementSpec as _MS

        if spec is None:
            spec = _MS(
                tool="http_client",
                completion="response",
                timeout_ms=int(timeout_s * 1000),
            )
        return self.measure(url, spec)

    @abstractmethod
    def measure_productivity(
        self,
        url: str,
        *,
        spec: "MeasurementSpec | None" = None,
        scenario: str = "page_load",
        wait_until: str = "networkidle",
        timeout_ms: int = 30000,
    ) -> "QoEResult":
        """Measure TTFB and page-load time for a productivity web application.

        Launches a headless Chromium browser, navigates to *url*, waits for the
        specified browser lifecycle event, and extracts Navigation Timing API
        metrics.

        **Wait strategies** (select based on what the use case measures):

        - ``"networkidle"`` — wait until no network connections for 500 ms.
          Use for session-continuity tests where all assets must be loaded
          (e.g. failover scenarios that re-measure after path switch).
        - ``"load"`` — wait for the browser ``load`` event
          (``loadEventEnd`` in Navigation Timing).  Use for page-load SLO
          tests that measure TTFB and total load time under varying WAN
          conditions.  More resilient to slow sub-resource loading.
        - ``"domcontentloaded"`` — wait for ``DOMContentLoaded`` only.
          Use when measuring perceived interactivity (DOM ready), not full
          page load.

        Populated fields in the returned :class:`~boardfarm3.lib.qoe.QoEResult`:

        - :attr:`~boardfarm3.lib.qoe.QoEResult.ttfb_ms` — ``responseStart - requestStart``.
        - :attr:`~boardfarm3.lib.qoe.QoEResult.load_time_ms` — ``loadEventEnd - navigationStart``.
        - :attr:`~boardfarm3.lib.qoe.QoEResult.protocol` — ``nextHopProtocol`` (Phase 3.5+).
        - :attr:`~boardfarm3.lib.qoe.QoEResult.success` — ``False`` for HTTP 4xx/5xx or
          network errors; ``True`` for 2xx/3xx.

        :param url: Target URL (e.g. ``"http://productivity.internal/"``).
        :param scenario: Scenario label for logging; does not affect measurement (default
            ``"page_load"``).  Future values: ``"login_flow"``, ``"file_download"``.
        :param wait_until: Browser lifecycle event to wait for before extracting
            Navigation Timing metrics.  One of ``"networkidle"``, ``"load"``,
            ``"domcontentloaded"`` (default ``"networkidle"``).
        :param timeout_ms: Maximum time to wait for the page to reach the
            *wait_until* event (milliseconds).  Set to at least the expected
            SLO load time + buffer for impaired conditions (default 30000).
        :return: :class:`~boardfarm3.lib.qoe.QoEResult` with productivity fields populated.
        """
        raise NotImplementedError

    @abstractmethod
    def measure_streaming(
        self,
        stream_url: str,
        *,
        spec: "MeasurementSpec | None" = None,
        duration_s: int = 30,
    ) -> "QoEResult":
        """Measure video startup time and rebuffer ratio for an HLS stream.

        Fetches the HLS manifest, downloads the first media segment to determine
        startup latency, and optionally monitors buffering events during *duration_s*
        seconds of simulated playback.

        Populated fields in the returned :class:`~boardfarm3.lib.qoe.QoEResult`:

        - :attr:`~boardfarm3.lib.qoe.QoEResult.startup_time_ms` — time from first request
          to first media segment downloaded (ms).
        - :attr:`~boardfarm3.lib.qoe.QoEResult.rebuffer_ratio` — fraction of *duration_s*
          spent buffering (0.0 in Phase 1; full measurement in Phase 3+).
        - :attr:`~boardfarm3.lib.qoe.QoEResult.success` — ``False`` if manifest or first
          segment is unreachable.

        :param stream_url: HLS manifest URL
            (e.g. ``"http://streaming.internal/live/stream.m3u8"``).
        :param duration_s: Simulated playback duration in seconds (default 30).
        :return: :class:`~boardfarm3.lib.qoe.QoEResult` with streaming fields populated.
        """
        raise NotImplementedError

    @abstractmethod
    def measure_conferencing(
        self,
        session_url: str,
        *,
        spec: "MeasurementSpec | None" = None,
        duration_s: int = 60,
    ) -> "QoEResult":
        """Measure RTT, jitter, packet-loss, and MOS for a WebRTC conferencing session.

        Connects to the WebRTC echo server at *session_url* via Playwright, runs a
        ``RTCPeerConnection`` session for *duration_s* seconds, calls
        ``getStats()``, and computes MOS using :func:`~boardfarm3.lib.qoe.calculate_mos`.

        Populated fields in the returned :class:`~boardfarm3.lib.qoe.QoEResult`:

        - :attr:`~boardfarm3.lib.qoe.QoEResult.latency_ms` — average RTT / 2 (ms).
        - :attr:`~boardfarm3.lib.qoe.QoEResult.jitter_ms` — average jitter from
          ``RTCInboundRtpStreamStats.jitter`` (ms).
        - :attr:`~boardfarm3.lib.qoe.QoEResult.packet_loss_pct` — inbound packet loss (%).
        - :attr:`~boardfarm3.lib.qoe.QoEResult.mos_score` — E-model MOS (1.0–4.5).
        - :attr:`~boardfarm3.lib.qoe.QoEResult.success` — ``False`` if connection fails or
          if the server is not reachable.

        :param session_url: WebRTC signaling endpoint URL
            (e.g. ``"ws://conf-server.internal:8080/session"``).
        :param duration_s: Session duration for stat accumulation (default 60).
        :return: :class:`~boardfarm3.lib.qoe.QoEResult` with conferencing fields populated.
        """
        raise NotImplementedError

    @abstractmethod
    def attempt_outbound_connection(
        self,
        host: str,
        port: int,
        *,
        timeout_s: float = 5.0,
    ) -> bool:
        """Attempt a TCP connection to *host*:*port* and return success.

        Used by security use-case assertions to verify that a WAN Edge appliance
        correctly allows or blocks outbound connections.  Returns ``True`` if the
        TCP three-way handshake completes (connection allowed), ``False`` if it does
        not (connection blocked, refused, or timed out).

        The method **never raises** — all outcomes (refused, timeout, error) map to
        ``False``.  Only a successful TCP connection returns ``True``.

        :param host: Target hostname or IP address.
        :param port: Target TCP port.
        :param timeout_s: Connection timeout in seconds (default 5.0).
        :return: ``True`` if TCP connection established; ``False`` otherwise.
        """
        raise NotImplementedError
