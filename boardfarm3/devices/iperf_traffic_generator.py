"""Boardfarm iPerf3 Traffic Generator device module.

Implements :class:`~boardfarm3.templates.traffic_generator.TrafficGenerator` using
iPerf3 on a dedicated ``traffic-gen`` Docker container.  Each instance is both a traffic
source (iPerf3 client) and a traffic sink (iPerf3 server pool).

**Dual-role container:**

The ``traffic-gen`` container boots with 10 iPerf3 server daemons (ports 5201-5210),
allowing up to 10 concurrent inbound flows.  The device driver manages outbound flows
by spawning background iPerf3 client processes on demand.

**Multi-flow support:**

Each :meth:`start_traffic` call spawns an independent iPerf3 client process with its
own PID file and JSON result file, identified by a ``flow_id``.  Multiple flows can
run concurrently from a single device instance.

**Inventory configuration:**

Required keys in the Boardfarm inventory JSON::

    {
      "name": "lan_traffic_gen",
      "type": "iperf_traffic_generator",
      "connection_type": "authenticated_ssh",
      "ipaddr": "localhost",
      "port": 5008,
      "username": "root",
      "password": "boardfarm",
      "simulated_ip": "192.168.10.20"
    }

``simulated_ip`` is the container's IP on the simulated network segment -- the address
other generators use as :attr:`TrafficSpec.destination`.

See: ``docs/examples/sdwan-digital-twin/future/traffic-generator.md``
"""

from __future__ import annotations

import json
import logging
import time
from argparse import Namespace

from boardfarm3 import hookimpl
from boardfarm3.devices.base_devices.linux_device import LinuxDevice
from boardfarm3.templates.traffic_generator import (
    TrafficGenerator,
    TrafficResult,
    TrafficSpec,
)

_LOGGER = logging.getLogger(__name__)

_SERVER_PORT_START = 5201
_SERVER_PORT_END = 5211
_SERVER_PORTS = list(range(_SERVER_PORT_START, _SERVER_PORT_END))


class IperfTrafficGenerator(LinuxDevice, TrafficGenerator):
    """Boardfarm iPerf3 traffic generator device.

    Standalone SSH container running iPerf3 for background load generation with DSCP
    marking.  Manages a pool of iPerf3 server processes (ports 5201-5210) and tracks
    multiple concurrent outbound client flows.

    Uses :class:`~boardfarm3.devices.base_devices.linux_device.LinuxDevice` SSH
    connection (``connection_type: authenticated_ssh``).  Inventory keys:
    ``ipaddr``, ``port``, ``username`` (default ``root``), ``password`` (default
    ``boardfarm``), ``simulated_ip`` (network-side IP for server targeting).
    """

    def __init__(self, config: dict, cmdline_args: Namespace) -> None:
        """Initialize iPerf3 Traffic Generator.

        :param config: Merged device config (inventory + env_def).
        :param cmdline_args: Boardfarm CLI arguments.
        """
        super().__init__(config, cmdline_args)
        self._flows: dict[str, dict] = {}
        self._flow_counter: int = 0

    @property
    def _simulated_ip(self) -> str:
        """Container's IP on the simulated network (from device config)."""
        return self._config["simulated_ip"]

    # ------------------------------------------------------------------
    # TrafficGenerator interface
    # ------------------------------------------------------------------

    def start_traffic(self, spec: TrafficSpec) -> str:
        """Start a background iPerf3 client flow.  Non-blocking.

        Spawns an iPerf3 client process in the background.  The process writes JSON
        results to a per-flow file on completion.

        :param spec: Traffic parameters.
        :return: Opaque flow identifier (e.g. ``"flow_0"``).
        """
        flow_id = f"flow_{self._flow_counter}"
        self._flow_counter += 1

        port = spec.port if spec.port is not None else self._allocate_port(spec.destination)
        result_file = f"/tmp/iperf3_{flow_id}_result.json"

        cmd = self._build_iperf3_cmd(spec, flow_id, port, result_file)
        _LOGGER.info(
            "%s: starting flow %s -> %s:%d (%s Mbps, DSCP %d)",
            self.device_name, flow_id, spec.destination, port,
            spec.bandwidth_mbps, spec.dscp,
        )
        self._console.execute_command(cmd)

        self._flows[flow_id] = {
            "result_file": result_file,
            "port": port,
            "destination": spec.destination,
            "dscp": spec.dscp,
        }
        return flow_id

    def stop_traffic(self, flow_id: str) -> TrafficResult:  # type: ignore[override]
        """Stop a specific iPerf3 client flow and return its results.

        Overrides ``LinuxDevice.stop_traffic(pid)`` -- the TrafficGenerator template
        interface takes precedence on this device type.

        :param flow_id: Identifier returned by :meth:`start_traffic`.
        :return: :class:`TrafficResult` with achieved rates and loss statistics.
        :raises KeyError: if *flow_id* is not in the active flows set.
        """
        if flow_id not in self._flows:
            msg = (
                f"Flow {flow_id!r} not found on {self.device_name!r}. "
                f"Active flows: {list(self._flows)}"
            )
            raise KeyError(msg)
        flow = self._flows.pop(flow_id)

        _LOGGER.info("%s: stopping flow %s", self.device_name, flow_id)
        self._console.execute_command(
            f"pkill -f 'iperf3.*{flow_id}' 2>/dev/null || true"
        )
        time.sleep(0.5)

        return self._read_flow_result(flow)

    def stop_all_traffic(self) -> dict[str, TrafficResult]:
        """Stop ALL active iPerf3 client flows and return results for each.

        :return: ``{flow_id: TrafficResult}`` for every flow that was active.
        """
        if not self._flows:
            return {}

        _LOGGER.info(
            "%s: stopping all flows (%d active)", self.device_name, len(self._flows),
        )
        self._console.execute_command(
            "pkill -f 'iperf3.*--logfile /tmp/iperf3_flow_' 2>/dev/null || true"
        )
        time.sleep(0.5)

        results: dict[str, TrafficResult] = {}
        for fid, flow in list(self._flows.items()):
            results[fid] = self._read_flow_result(flow)
        self._flows.clear()
        return results

    def run_traffic(self, spec: TrafficSpec) -> TrafficResult:
        """Run a single iPerf3 flow to completion.  Blocking.

        :param spec: Traffic parameters.
        :return: :class:`TrafficResult` with achieved rates and loss statistics.
        """
        flow_id = self.start_traffic(spec)
        time.sleep(spec.duration_s + 2)
        return self.stop_traffic(flow_id)

    @property
    def server_ip(self) -> str:
        """IP address of the iPerf3 server pool on the simulated network."""
        return self._simulated_ip

    @property
    def active_flows(self) -> list[str]:
        """List of currently active flow identifiers."""
        return list(self._flows)

    # ------------------------------------------------------------------
    # Boardfarm hooks
    # ------------------------------------------------------------------

    @hookimpl
    def boardfarm_skip_boot(self) -> None:
        """Connect and verify iPerf3 server pool is running (skip-boot path)."""
        _LOGGER.info("Initializing %s (%s)", self.device_name, self.device_type)
        self._validate_config()
        self._connect()
        self._ensure_server_pool()

    @hookimpl
    async def boardfarm_skip_boot_async(self) -> None:
        """Connect and verify iPerf3 server pool -- async variant."""
        _LOGGER.info("Initializing %s (%s)", self.device_name, self.device_type)
        self._validate_config()
        await self._connect_async()
        self._ensure_server_pool()

    @hookimpl
    def boardfarm_device_boot(self, device_manager: object) -> None:  # pylint: disable=unused-argument
        """Connect and start iPerf3 server pool (full-boot path)."""
        _LOGGER.info("Booting %s (%s)", self.device_name, self.device_type)
        self._validate_config()
        self._connect()
        self._ensure_server_pool()

    @hookimpl
    async def boardfarm_device_boot_async(self, device_manager: object) -> None:  # pylint: disable=unused-argument
        """Connect and start iPerf3 server pool -- async variant."""
        _LOGGER.info("Booting %s (%s)", self.device_name, self.device_type)
        self._validate_config()
        await self._connect_async()
        self._ensure_server_pool()

    @hookimpl
    def boardfarm_shutdown_device(self) -> None:
        """Stop all flows and disconnect."""
        _LOGGER.info("Shutdown %s (%s)", self.device_name, self.device_type)
        if self._flows:
            self.stop_all_traffic()
        self._disconnect()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_config(self) -> None:
        """Verify required config keys are present before boot.

        :raises KeyError: if ``simulated_ip`` is absent in device config.
        """
        if "simulated_ip" not in self._config:
            msg = (
                f"Device {self.device_name!r} ({self.device_type!r}): "
                "'simulated_ip' is required. "
                "Set it in the Boardfarm inventory JSON to the IP address "
                "of the container on the simulated network, "
                'e.g.: "simulated_ip": "192.168.10.20"'
            )
            raise KeyError(msg)

    def _ensure_server_pool(self) -> None:
        """Start iPerf3 server daemons on ports 5201-5210 if not already running."""
        for port in _SERVER_PORTS:
            pid_file = f"/run/iperf3_{port}.pid"
            check = self._console.execute_command(
                f"test -f {pid_file} && kill -0 $(cat {pid_file}) 2>/dev/null"
                " && echo RUNNING || echo STOPPED"
            )
            if "RUNNING" not in check:
                self._console.execute_command(
                    f"iperf3 --server --daemon --pidfile {pid_file} --port {port}"
                )
                _LOGGER.debug(
                    "%s: started iPerf3 server on port %d", self.device_name, port,
                )

    def _allocate_port(self, destination: str) -> int:
        """Auto-allocate a server port not already used by active flows to *destination*.

        :param destination: Target IP address.
        :return: Available port number from the server pool range.
        :raises RuntimeError: if all ports to *destination* are in use.
        """
        used = {
            f["port"] for f in self._flows.values()
            if f["destination"] == destination
        }
        for port in _SERVER_PORTS:
            if port not in used:
                return port
        msg = (
            f"All {len(_SERVER_PORTS)} server ports to {destination} are in use on "
            f"{self.device_name!r}. Stop some flows first."
        )
        raise RuntimeError(msg)

    @staticmethod
    def _build_iperf3_cmd(
        spec: TrafficSpec,
        flow_id: str,
        port: int,
        result_file: str,
    ) -> str:
        """Build the iPerf3 client command string.

        :param spec: Traffic parameters.
        :param flow_id: Unique flow identifier (used in process title for pkill).
        :param port: Target server port.
        :param result_file: Path on the remote device for JSON output.
        :return: Shell command string.
        """
        tos = spec.dscp << 2
        parts = [
            "iperf3",
            "--client", spec.destination,
            "--port", str(port),
            "--time", str(spec.duration_s),
            "--bandwidth", f"{spec.bandwidth_mbps}M",
            "--tos", str(tos),
            "--json",
            "--logfile", result_file,
            "--forceflush",
            f"--title {flow_id}",
        ]
        if spec.protocol == "udp":
            parts.append("--udp")
        if spec.parallel_streams > 1:
            parts.extend(["--parallel", str(spec.parallel_streams)])

        cmd = " ".join(parts)
        return f"nohup {cmd} > /dev/null 2>&1 &"

    def _read_flow_result(self, flow: dict) -> TrafficResult:
        """Read and parse the iPerf3 JSON result file for a completed flow.

        :param flow: Flow metadata dict (from ``self._flows``).
        :return: Parsed :class:`TrafficResult`, or a zero-valued result on parse failure.
        """
        result_file = flow["result_file"]
        raw = self._console.execute_command(f"cat {result_file} 2>/dev/null || echo '{{}}'")
        self._console.execute_command(f"rm -f {result_file}")
        return self._parse_iperf3_json(raw, dscp=flow.get("dscp", 0))

    @staticmethod
    def _parse_iperf3_json(raw: str, dscp: int = 0) -> TrafficResult:
        """Parse iPerf3 JSON output into a :class:`TrafficResult`.

        When iPerf3 is killed mid-flow (``--forceflush`` + ``--logfile``), the
        result file may contain multiple concatenated JSON documents from
        incremental flushes.  We decode them all and use the **last** one that
        contains an ``"end"`` summary block (the final report written on
        termination).  Falls back to the last successfully parsed object if
        none contain ``"end"``.

        :param raw: Raw JSON string from iPerf3 ``--json`` output.
        :param dscp: DSCP value that was configured for this flow.
        :return: Parsed :class:`TrafficResult`.
        """
        idx = raw.find("{")
        if idx < 0:
            _LOGGER.warning("No JSON found in iPerf3 output")
            return TrafficResult(dscp_marking=dscp)

        decoder = json.JSONDecoder()
        documents: list[dict] = []
        pos = idx
        while pos < len(raw):
            next_brace = raw.find("{", pos)
            if next_brace < 0:
                break
            try:
                obj, end_idx = decoder.raw_decode(raw, next_brace)
                documents.append(obj)
                pos = end_idx
            except json.JSONDecodeError:
                pos = next_brace + 1

        if not documents:
            _LOGGER.warning("Failed to parse any JSON from iPerf3 output")
            return TrafficResult(dscp_marking=dscp)

        data = next(
            (d for d in reversed(documents) if "end" in d),
            documents[-1],
        )

        end = data.get("end", {})
        sum_sent = end.get("sum_sent", {})
        sum_received = end.get("sum_received", {})
        sum_udp = end.get("sum", {})

        sent_bps = sum_sent.get("bits_per_second", 0.0)
        recv_bps = sum_received.get("bits_per_second", sum_udp.get("bits_per_second", 0.0))
        loss_pct = sum_udp.get("lost_percent", sum_sent.get("lost_percent", 0.0))
        jitter_ms = sum_udp.get("jitter_ms")

        return TrafficResult(
            sent_mbps=sent_bps / 1_000_000,
            received_mbps=recv_bps / 1_000_000,
            loss_percent=loss_pct,
            jitter_ms=jitter_ms,
            dscp_marking=dscp,
        )
