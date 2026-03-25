"""Boardfarm TrafficGenerator device template.

Defines the abstract interface for background traffic load generators used in QoS
contention and bandwidth saturation tests.  Use cases depend only on this interface --
concrete implementations (iPerf3, hardware appliances) are interchangeable.

**Purpose vs. legacy iperf:**

This template is purpose-built for *background load injection* with DSCP marking and an
asynchronous start/stop model.  It does **not** replace the legacy
:mod:`~boardfarm3.use_cases.iperf` module, which handles LAN/WAN throughput testing on
:class:`~boardfarm3.templates.lan.LAN` / :class:`~boardfarm3.templates.wan.WAN` devices.

**Multi-flow design:**

A single TrafficGenerator instance can run multiple concurrent outbound flows, each
identified by a ``flow_id`` returned from :meth:`TrafficGenerator.start_traffic`.  This
enables one-to-many (single source, multiple destinations) and many-to-many patterns
without extra container instances.

**Dual-role (client + server):**

Each instance also runs an iPerf3 server pool at boot, so it can act as both a traffic
source (client) and a traffic sink (server).  The :attr:`TrafficGenerator.server_ip`
property exposes the address other generators should target.

See: ``docs/examples/sdwan-digital-twin/future/traffic-generator.md``
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TrafficSpec:
    """Parameters for a single traffic flow.

    :param destination: Target IP address (typically another generator's
        :attr:`~TrafficGenerator.server_ip`).
    :param bandwidth_mbps: Target send rate in Mbps.
    :param protocol: Transport protocol (``"udp"`` or ``"tcp"``).
    :param dscp: DSCP code point (0-63).  Converted to TOS byte by the implementation
        (``tos = dscp << 2``).  Default 0 (best effort).
    :param duration_s: Flow duration in seconds.  Used by
        :meth:`~TrafficGenerator.run_traffic` (blocking) and as a safety timeout for
        :meth:`~TrafficGenerator.start_traffic` (non-blocking).
    :param parallel_streams: Number of parallel streams within this flow (iPerf3 ``-P``).
    :param port: Target server port.  When ``None``, the implementation auto-allocates
        from the server pool.
    """

    destination: str
    bandwidth_mbps: float
    protocol: str = "udp"
    dscp: int = 0
    duration_s: int = 30
    parallel_streams: int = 1
    port: int | None = None


@dataclass
class TrafficResult:
    """Measured results from a completed traffic flow.

    :param sent_mbps: Achieved send rate in Mbps.
    :param received_mbps: Achieved receive rate in Mbps.
    :param loss_percent: Packet loss as a percentage (0.0 - 100.0).
    :param jitter_ms: Jitter in milliseconds (UDP only; ``None`` for TCP).
    :param dscp_marking: DSCP value that was configured for the flow.
    """

    sent_mbps: float = 0.0
    received_mbps: float = 0.0
    loss_percent: float = 0.0
    jitter_ms: float | None = None
    dscp_marking: int = 0


class TrafficGenerator(ABC):
    """Abstract background load generator for QoS and contention tests.

    Supports multiple concurrent flows per device instance, enabling
    one-to-many and many-to-many traffic patterns from a single generator.

    Implementations (e.g.
    :class:`~boardfarm3.devices.iperf_traffic_generator.IperfTrafficGenerator`)
    connect via SSH and use iPerf3 CLI commands.

    **Async model:** :meth:`start_traffic` is non-blocking and returns a ``flow_id``.
    The typical test pattern is::

        fid = generator.start_traffic(spec)
        # ... measure priority traffic QoE ...
        result = generator.stop_traffic(fid)

    **Failure semantics:** :meth:`start_traffic` and :meth:`run_traffic` raise on
    configuration errors (unreachable destination, invalid spec).  :meth:`stop_traffic`
    always returns a :class:`TrafficResult`, even if the flow ended prematurely.
    """

    @abstractmethod
    def start_traffic(self, spec: TrafficSpec) -> str:
        """Start a background traffic flow.  Non-blocking.

        :param spec: Traffic parameters (rate, protocol, DSCP, destination).
        :return: Opaque flow identifier.  Use with :meth:`stop_traffic` to stop
            this specific flow.
        """
        raise NotImplementedError

    @abstractmethod
    def stop_traffic(self, flow_id: str) -> TrafficResult:
        """Stop a specific flow and return its results.

        :param flow_id: Identifier returned by :meth:`start_traffic`.
        :return: :class:`TrafficResult` with achieved rates and loss statistics.
        :raises KeyError: if *flow_id* is not in the active flows set.
        """
        raise NotImplementedError

    @abstractmethod
    def stop_all_traffic(self) -> dict[str, TrafficResult]:
        """Stop ALL active flows and return results for each.

        Safe to call when no flows are active (returns empty dict).

        :return: ``{flow_id: TrafficResult}`` for every flow that was active.
        """
        raise NotImplementedError

    @abstractmethod
    def run_traffic(self, spec: TrafficSpec) -> TrafficResult:
        """Run a single traffic flow to completion.  Blocking.

        Equivalent to ``start_traffic(spec)`` + ``sleep(spec.duration_s)`` +
        ``stop_traffic(flow_id)``.

        :param spec: Traffic parameters.
        :return: :class:`TrafficResult` with achieved rates and loss statistics.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def server_ip(self) -> str:
        """IP address of the built-in server on this device.

        Used by other generators as :attr:`TrafficSpec.destination`.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def active_flows(self) -> list[str]:
        """List of currently active flow identifiers."""
        raise NotImplementedError
