"""Boardfarm PlaywrightQoEClient device module.

Implements :class:`~boardfarm3.templates.qoe_client.QoEClient` using Playwright +
Chromium running inside the ``lan-qoe-client`` Docker container.  Measurements are
executed by writing Python scripts to the remote container via SSH and parsing
JSON from stdout.

**Remote script execution pattern:**

Playwright scripts are base64-encoded on the boardfarm host, decoded on the remote
device, and executed with ``python3``.  This avoids all shell-escaping complexity::

    1. Python script string → base64 bytes → decoded and written to /tmp/bf_qoe_script.py
    2. python3 /tmp/bf_qoe_script.py → JSON line on stdout
    3. _parse_json_result() extracts and parses the JSON from raw console output

**Container requirements:**

The ``lan-qoe-client`` container must have:

- ``playwright`` Python package installed (``playwright install chromium``).
- ``chromium`` browser installed (included in Playwright install).
- Raikou-injected LAN interface (``eth-lan``) connected to the ``lan-segment`` OVS bridge.
- Default route via the DUT's LAN IP (``192.168.10.1`` on ``eth-lan``).

**Inventory configuration:**

Required keys in the Boardfarm inventory JSON::

    {
      "name": "lan_qoe_client",
      "type": "playwright_qoe_client",
      "connection_type": "authenticated_ssh",
      "ipaddr": "localhost",
      "port": 5003,
      "username": "root",
      "password": "boardfarm",
      "simulated_ip": "192.168.10.10"
    }

``simulated_ip`` is the LAN-side address of the container on the simulated network
(not the Docker management-network address used for SSH).

See: ``docs/QoE_Client_Implementation_Plan.md``
"""

from __future__ import annotations

import base64
import json
import logging
import textwrap
from argparse import Namespace

from boardfarm3 import hookimpl
from boardfarm3.devices.base_devices.linux_device import LinuxDevice
from boardfarm3.lib.qoe import QoEResult, calculate_mos
from boardfarm3.templates.qoe_client import QoEClient

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Remote Playwright scripts (executed via python3 on the lan-qoe-client container)
# ---------------------------------------------------------------------------

_PRODUCTIVITY_SCRIPT = textwrap.dedent("""
    import asyncio
    import json
    import sys
    from urllib.parse import urlparse

    URL = {url_repr}

    async def main():
        from playwright.async_api import async_playwright

        chromium_args = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--enable-quic",
        ]
        parsed = urlparse(URL)
        if parsed.scheme == "https":
            port = parsed.port or 443
            chromium_args.append(f"--origin-to-force-quic-on={parsed.hostname}:{port}")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=chromium_args,
            )
            page = await browser.new_page()
            try:
                response = await page.goto(URL, wait_until="networkidle", timeout=30000)
                status = response.status if response else 0
                timing = await page.evaluate(
                    \"\"\"() => {
                        const t = window.performance.timing;
                        const nav = window.performance.getEntriesByType('navigation')[0];
                        const ttfb = t.responseStart > 0
                            ? t.responseStart - t.requestStart
                            : null;
                        const load = t.loadEventEnd > 0
                            ? t.loadEventEnd - t.navigationStart
                            : null;
                        return {
                            ttfb_ms: ttfb,
                            load_time_ms: load,
                            protocol: nav ? nav.nextHopProtocol : null
                        };
                    }\"\"\"
                )
                print(json.dumps({
                    "ttfb_ms":      timing.get("ttfb_ms"),
                    "load_time_ms": timing.get("load_time_ms"),
                    "protocol":     timing.get("protocol"),
                    "success":      200 <= status < 400,
                }))
            except Exception as exc:
                print(json.dumps({
                    "ttfb_ms": None, "load_time_ms": None,
                    "protocol": None, "success": False, "error": str(exc),
                }))
            finally:
                await browser.close()

    asyncio.run(main())
""").strip()

_STREAMING_SCRIPT = textwrap.dedent("""
    import asyncio
    import json
    import time
    import urllib.request

    STREAM_URL = {stream_url_repr}
    DURATION_S  = {duration_s}

    def _fetch_timing(url, timeout=30):
        \"\"\"Fetch *url*, return (elapsed_ms, status_code).\"\"\"
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                resp.read()
                elapsed = (time.monotonic() - t0) * 1000
                return elapsed, resp.status
        except Exception as exc:
            return None, str(exc)

    def _parse_m3u8_segments(content):
        \"\"\"Return the first relative or absolute segment URL from an M3U8 manifest.\"\"\"
        lines = content.decode(errors="replace").splitlines()
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#"):
                return line
        return None

    def main():
        # 1. Fetch HLS manifest
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(STREAM_URL, timeout=30) as resp:
                manifest_content = resp.read()
                manifest_status = resp.status
        except Exception as exc:
            print(json.dumps({
                "startup_time_ms": None, "rebuffer_ratio": None,
                "success": False, "error": str(exc),
            }))
            return

        if manifest_status != 200:
            print(json.dumps({
                "startup_time_ms": None, "rebuffer_ratio": None,
                "success": False, "error": f"manifest HTTP {manifest_status}",
            }))
            return

        # 2. Find and fetch first media segment
        segment_path = _parse_m3u8_segments(manifest_content)
        if not segment_path:
            print(json.dumps({
                "startup_time_ms": None, "rebuffer_ratio": None,
                "success": False, "error": "no segment in manifest",
            }))
            return

        # Resolve relative segment URL against manifest base
        if segment_path.startswith("http"):
            segment_url = segment_path
        else:
            base = STREAM_URL.rsplit("/", 1)[0]
            segment_url = f"{base}/{segment_path}"

        elapsed_ms, seg_status = _fetch_timing(segment_url)
        if elapsed_ms is None:
            print(json.dumps({
                "startup_time_ms": None, "rebuffer_ratio": None,
                "success": False, "error": f"segment fetch failed: {seg_status}",
            }))
            return

        # startup_time_ms = total time from first request to first segment received
        startup_time_ms = (time.monotonic() - t0) * 1000

        # rebuffer_ratio: Phase 1 — returns 0.0 (requires HLS player for live tracking)
        print(json.dumps({
            "startup_time_ms": startup_time_ms,
            "rebuffer_ratio": 0.0,
            "success": True,
        }))

    main()
""").strip()

_CONFERENCING_SCRIPT = textwrap.dedent("""
    import asyncio
    import json

    SESSION_URL = {session_url_repr}
    DURATION_S  = {duration_s}

    async def main():
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--enable-quic",
                    "--use-fake-ui-for-media-stream",
                    "--use-fake-device-for-media-stream",
                    "--disable-features=ChromeRootStoreUsed",
                ],
            )
            page = await browser.new_page()
            page.set_default_timeout((DURATION_S + 15) * 1000)
            try:
                # Inject a WebRTC echo session using the pion signaling WebSocket.
                # The session_url is the WebSocket signaling endpoint (e.g. ws://...).
                stats = await page.evaluate(
                    \"\"\"async ([sessionUrl, durationS]) => {
                        return new Promise(async (resolve) => {
                            const ws = new WebSocket(sessionUrl);
                            let pc = null;
                            let resolved = false;

                            function finish(result) {
                                if (!resolved) {
                                    resolved = true;
                                    if (pc) pc.close();
                                    if (ws.readyState === WebSocket.OPEN) ws.close();
                                    resolve(result);
                                }
                            }

                            const timeout = setTimeout(() => {
                                finish({success: false, error: "connection timeout"});
                            }, 10000);

                            ws.onopen = async () => {
                                clearTimeout(timeout);
                                pc = new RTCPeerConnection({iceServers: []});

                                // Add a fake audio track so the peer connection has media
                                const ctx = new AudioContext();
                                const osc = ctx.createOscillator();
                                const dst = ctx.createMediaStreamDestination();
                                osc.connect(dst);
                                osc.start();
                                dst.stream.getTracks().forEach(t => pc.addTrack(t, dst.stream));

                                pc.onicecandidate = (e) => {
                                    if (e.candidate && ws.readyState === WebSocket.OPEN) {
                                        ws.send(JSON.stringify({type: "candidate", candidate: e.candidate}));
                                    }
                                };

                                const offer = await pc.createOffer();
                                await pc.setLocalDescription(offer);
                                ws.send(JSON.stringify({type: "offer", sdp: offer.sdp}));
                            };

                            ws.onmessage = async (evt) => {
                                const msg = JSON.parse(evt.data);
                                if (msg.type === "answer") {
                                    await pc.setRemoteDescription(
                                        new RTCSessionDescription({type: "answer", sdp: msg.sdp})
                                    );
                                    // Measure stats after durationS seconds
                                    setTimeout(async () => {
                                        try {
                                            const statsReport = await pc.getStats();
                                            let rttMs = null, iceRttMs = null, jitterMs = null, lossAbs = null, sent = null;
                                            statsReport.forEach(s => {
                                                if (s.type === "remote-inbound-rtp") {
                                                    if (s.roundTripTime != null) rttMs = s.roundTripTime * 1000;
                                                    if (s.jitter != null) jitterMs = s.jitter * 1000;
                                                    if (s.packetsLost != null) lossAbs = s.packetsLost;
                                                }
                                                if (s.type === "candidate-pair" && s.state === "succeeded") {
                                                    if (s.currentRoundTripTime != null) iceRttMs = s.currentRoundTripTime * 1000;
                                                }
                                                if (s.type === "outbound-rtp") {
                                                    if (s.packetsSent != null) sent = s.packetsSent;
                                                }
                                            });
                                            const bestRtt = rttMs != null ? rttMs : iceRttMs;
                                            const lossPct = (sent && lossAbs != null && sent > 0)
                                                ? (lossAbs / (sent + lossAbs)) * 100
                                                : 0.0;
                                            finish({
                                                success: true,
                                                latency_ms: bestRtt != null ? bestRtt / 2 : null,
                                                jitter_ms: jitterMs,
                                                packet_loss_pct: lossPct,
                                            });
                                        } catch(e) {
                                            finish({success: false, error: String(e)});
                                        }
                                    }, durationS * 1000);
                                } else if (msg.type === "candidate" && pc) {
                                    await pc.addIceCandidate(msg.candidate).catch(() => {});
                                }
                            };

                            ws.onerror = (e) => finish({success: false, error: "websocket error"});
                        });
                    }\"\"\",
                    [SESSION_URL, DURATION_S],
                )
                print(json.dumps(stats))
            except Exception as exc:
                print(json.dumps({
                    "success": False, "error": str(exc),
                    "latency_ms": None, "jitter_ms": None, "packet_loss_pct": None,
                }))
            finally:
                await browser.close()

    asyncio.run(main())
""").strip()

_OUTBOUND_CONN_SCRIPT = textwrap.dedent("""
    import json
    import socket

    HOST    = {host_repr}
    PORT    = {port}
    TIMEOUT = {timeout_s}

    try:
        s = socket.create_connection((HOST, PORT), timeout=TIMEOUT)
        s.close()
        print(json.dumps({"connected": True}))
    except Exception as exc:
        print(json.dumps({"connected": False, "error": str(exc)}))
""").strip()


# ---------------------------------------------------------------------------
# JSON output parser
# ---------------------------------------------------------------------------


def _parse_json_result(raw: str) -> dict:
    """Extract and parse the JSON result line from remote script stdout.

    The raw console output may contain a command echo, shell prompts, or log
    lines before and after the JSON.  We scan for the last ``{`` to tolerate this.

    :param raw: Raw console output from the remote ``python3`` invocation.
    :return: Parsed dict, or ``{"success": False, "error": "..."}`` on failure.
    """
    raw = raw.strip()
    idx = raw.rfind("{")
    if idx < 0:
        _LOGGER.warning("No JSON object found in QoE script output: %r", raw[:300])
        return {"success": False, "error": "no JSON in output"}
    try:
        return json.loads(raw[idx:])  # type: ignore[no-any-return]
    except json.JSONDecodeError as exc:
        _LOGGER.warning("Failed to parse QoE JSON: %r (%s)", raw[idx:idx + 200], exc)
        return {"success": False, "error": f"json parse error: {exc}"}


# ---------------------------------------------------------------------------
# Device class
# ---------------------------------------------------------------------------


class PlaywrightQoEClient(LinuxDevice, QoEClient):
    """Boardfarm QoE measurement device using Playwright + Chromium.

    Executes headless Chromium measurements on the ``lan-qoe-client`` container via SSH.
    Implements all four methods of the :class:`~boardfarm3.templates.qoe_client.QoEClient`
    template.

    Each measurement compiles a self-contained Python script, writes it to the remote
    device via a base64 channel, executes it, and parses the JSON result from stdout.

    Uses :class:`~boardfarm3.devices.base_devices.linux_device.LinuxDevice` SSH
    connection (``connection_type: authenticated_ssh``).  Inventory keys:
    ``ipaddr``, ``port``, ``username`` (default ``root``), ``password`` (default
    ``boardfarm``), ``simulated_ip`` (LAN-side IP, used by :attr:`ip_address`).
    """

    def __init__(self, config: dict, cmdline_args: Namespace) -> None:
        """Initialize PlaywrightQoEClient.

        :param config: Merged device config (inventory + env_def).  Must include
            ``simulated_ip`` — the LAN-side IP address on the simulated network.
        :param cmdline_args: Boardfarm CLI arguments.
        :raises KeyError: if ``simulated_ip`` is absent in *config*.
        """
        super().__init__(config, cmdline_args)
        if "simulated_ip" not in config:
            raise KeyError(
                f"Device {self.device_name!r} ({self.device_type!r}): "
                "'simulated_ip' is required. "
                "Set it in the Boardfarm inventory JSON to the LAN-side IP "
                "of the container on the simulated network, "
                "e.g.: \"simulated_ip\": \"192.168.10.10\""
            )
        self._simulated_ip: str = config["simulated_ip"]

    # ------------------------------------------------------------------
    # QoEClient interface — ip_address property
    # ------------------------------------------------------------------

    @property
    def ip_address(self) -> str:
        """LAN-side IP address on the simulated network (from ``simulated_ip`` inventory key)."""
        return self._simulated_ip

    # ------------------------------------------------------------------
    # QoEClient interface — measurement methods
    # ------------------------------------------------------------------

    def measure_productivity(
        self,
        url: str,
        *,
        scenario: str = "page_load",
    ) -> QoEResult:
        """Measure TTFB and page-load time via Playwright Navigation Timing API.

        :param url: Target URL (e.g. ``"http://productivity.internal/"``).
        :param scenario: Scenario label for log output (default ``"page_load"``).
        :return: :class:`~boardfarm3.lib.qoe.QoEResult` with productivity fields set.
        """
        _LOGGER.info(
            "%s: measure_productivity(url=%r, scenario=%r)",
            self.device_name, url, scenario,
        )
        script = _PRODUCTIVITY_SCRIPT.replace("{url_repr}", repr(url))
        raw = self._run_script(script, timeout=60)
        data = _parse_json_result(raw)
        return QoEResult(
            ttfb_ms=data.get("ttfb_ms"),
            load_time_ms=data.get("load_time_ms"),
            protocol=data.get("protocol"),
            success=bool(data.get("success", False)),
        )

    def measure_streaming(
        self,
        stream_url: str,
        *,
        duration_s: int = 30,
    ) -> QoEResult:
        """Measure video startup time for an HLS stream via segment fetch timing.

        Fetches the HLS manifest and first media segment using Python's
        ``urllib.request``.  Returns ``rebuffer_ratio = 0.0`` in Phase 1 (live
        rebuffer tracking requires an HLS player, added in Phase 3).

        :param stream_url: HLS manifest URL
            (e.g. ``"http://streaming.internal/live/stream.m3u8"``).
        :param duration_s: Simulated playback duration — passed to the script for
            future Phase 3 rebuffer measurement (default 30).
        :return: :class:`~boardfarm3.lib.qoe.QoEResult` with streaming fields set.
        """
        _LOGGER.info(
            "%s: measure_streaming(stream_url=%r, duration_s=%d)",
            self.device_name, stream_url, duration_s,
        )
        script = (
            _STREAMING_SCRIPT
            .replace("{stream_url_repr}", repr(stream_url))
            .replace("{duration_s}", str(duration_s))
        )
        raw = self._run_script(script, timeout=duration_s + 90)
        data = _parse_json_result(raw)
        return QoEResult(
            startup_time_ms=data.get("startup_time_ms"),
            rebuffer_ratio=data.get("rebuffer_ratio"),
            success=bool(data.get("success", False)),
        )

    def measure_conferencing(
        self,
        session_url: str,
        *,
        duration_s: int = 60,
    ) -> QoEResult:
        """Measure WebRTC RTT, jitter, packet-loss, and MOS via ``getStats()``.

        Launches Chromium with fake media devices, connects to the pion echo server
        at *session_url* via a WebSocket signaling exchange, runs a
        ``RTCPeerConnection`` session for *duration_s* seconds, and calls
        ``getStats()`` to extract ``remote-inbound-rtp`` statistics.

        MOS is calculated using :func:`~boardfarm3.lib.qoe.calculate_mos`.

        :param session_url: WebRTC signaling WebSocket URL
            (e.g. ``"ws://conf-server.internal:8080/session"``).
        :param duration_s: Session duration for stat accumulation (default 60).
        :return: :class:`~boardfarm3.lib.qoe.QoEResult` with conferencing fields set.
        """
        _LOGGER.info(
            "%s: measure_conferencing(session_url=%r, duration_s=%d)",
            self.device_name, session_url, duration_s,
        )
        script = (
            _CONFERENCING_SCRIPT
            .replace("{session_url_repr}", repr(session_url))
            .replace("{duration_s}", str(duration_s))
        )
        raw = self._run_script(script, timeout=duration_s + 30)
        data = _parse_json_result(raw)

        latency_ms = data.get("latency_ms")
        jitter_ms = data.get("jitter_ms")
        loss_pct = data.get("packet_loss_pct")

        mos: float | None = None
        if latency_ms is not None and jitter_ms is not None and loss_pct is not None:
            mos = calculate_mos(
                latency_ms=latency_ms,
                jitter_ms=jitter_ms,
                loss_percent=loss_pct,
            )

        return QoEResult(
            latency_ms=latency_ms,
            jitter_ms=jitter_ms,
            packet_loss_pct=loss_pct,
            mos_score=mos,
            success=bool(data.get("success", False)),
        )

    def attempt_outbound_connection(
        self,
        host: str,
        port: int,
        *,
        timeout_s: float = 5.0,
    ) -> bool:
        """Attempt a TCP connection from the LAN client to *host*:*port*.

        Uses Python's ``socket.create_connection()`` on the remote container so that
        traffic traverses the simulated network (eth-lan → DUT → WAN).

        :param host: Target hostname or IP address.
        :param port: Target TCP port.
        :param timeout_s: Connection timeout in seconds (default 5.0).
        :return: ``True`` if TCP handshake completes; ``False`` otherwise.
        """
        _LOGGER.info(
            "%s: attempt_outbound_connection(host=%r, port=%d, timeout_s=%.1f)",
            self.device_name, host, port, timeout_s,
        )
        script = (
            _OUTBOUND_CONN_SCRIPT
            .replace("{host_repr}", repr(host))
            .replace("{port}", str(port))
            .replace("{timeout_s}", str(timeout_s))
        )
        raw = self._run_script(script, timeout=int(timeout_s) + 10)
        data = _parse_json_result(raw)
        return bool(data.get("connected", False))

    # ------------------------------------------------------------------
    # Boardfarm hooks
    # ------------------------------------------------------------------

    @hookimpl
    def boardfarm_skip_boot(self) -> None:
        """Connect to the lan-qoe-client container (skip-boot path)."""
        _LOGGER.info("Initializing %s (%s)", self.device_name, self.device_type)
        self._connect()

    @hookimpl
    async def boardfarm_skip_boot_async(self) -> None:
        """Connect to the lan-qoe-client container — async variant."""
        _LOGGER.info("Initializing %s (%s)", self.device_name, self.device_type)
        await self._connect_async()

    @hookimpl
    def boardfarm_device_boot(self, device_manager: object) -> None:  # pylint: disable=unused-argument
        """Connect to the lan-qoe-client container (full-boot path)."""
        _LOGGER.info("Booting %s (%s)", self.device_name, self.device_type)
        self._connect()

    @hookimpl
    async def boardfarm_device_boot_async(self, device_manager: object) -> None:  # pylint: disable=unused-argument
        """Connect to the lan-qoe-client container — async variant."""
        _LOGGER.info("Booting %s (%s)", self.device_name, self.device_type)
        await self._connect_async()

    @hookimpl
    def boardfarm_shutdown_device(self) -> None:
        """Disconnect from the lan-qoe-client container."""
        _LOGGER.info("Shutdown %s (%s)", self.device_name, self.device_type)
        self._disconnect()

    # ------------------------------------------------------------------
    # Remote script execution helper
    # ------------------------------------------------------------------

    # Maximum base64 characters per chunk.  Each chunk is wrapped in a
    # ``printf '%s' '...' >> file`` command; with stty columns 400 the total
    # line length is 300 (chunk) + ~42 (command wrapper) = ~342 chars, safely
    # within the 400-column terminal so pexpect's expect_exact() will always
    # find the echo within a single line.
    _B64_CHUNK_SIZE: int = 300

    def _run_script(self, script: str, timeout: int = 60) -> str:
        """Write *script* to the remote device and execute it; return stdout.

        The script is base64-encoded to avoid all shell-escaping issues.  The
        encoded payload is written to a temp file on the remote in 300-character
        chunks (to stay within the terminal line length), decoded with
        ``base64 -d``, and executed with ``python3``.

        :param script: Python 3 source code for the measurement script.
        :param timeout: Execution timeout passed to ``execute_command`` (seconds).
        :return: Raw console output (stdout + stderr) from the script execution.
        """
        encoded = base64.b64encode(script.encode()).decode()

        # Clear the staging file, then append in short chunks so every
        # execute_command() call fits within one terminal line (≤400 cols).
        self._console.execute_command("truncate -s 0 /tmp/bf_qoe_encoded.b64")
        for i in range(0, len(encoded), self._B64_CHUNK_SIZE):
            chunk = encoded[i : i + self._B64_CHUNK_SIZE]
            self._console.execute_command(
                f"printf '%s' '{chunk}' >> /tmp/bf_qoe_encoded.b64"
            )

        # Decode the accumulated base64 file into the runnable Python script.
        self._console.execute_command(
            "base64 -d /tmp/bf_qoe_encoded.b64 > /tmp/bf_qoe_script.py"
        )
        return self._console.execute_command(
            "python3 /tmp/bf_qoe_script.py",
            timeout=timeout,
        )
