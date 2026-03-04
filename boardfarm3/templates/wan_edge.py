"""Boardfarm WAN Edge device template."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from boardfarm3.lib.boardfarm_pexpect import BoardfarmPexpect


@dataclass
class PathMetrics:
    """Per-link quality metrics as measured by the device."""

    latency_ms: float
    jitter_ms: float
    loss_percent: float
    link_name: str


@dataclass
class LinkStatus:
    """Operational state of a WAN interface."""

    name: str
    state: str  # "up" | "down" | "degraded"
    ip_address: str


@dataclass
class RouteEntry:
    """Single entry in the routing table."""

    destination: str
    gateway: str
    interface: str
    metric: int


class WANEdgeDevice(ABC):
    """Abstract interface for WAN Edge / SD-WAN appliances.

    Implementations: LinuxSDWANRouter, CiscoC8000DUT, FortiGateDUT, VelocloudDUT.
    """

    @property
    @abstractmethod
    def nbi(self) -> Any:
        """Northbound Interface - Orchestrator REST API."""
        raise NotImplementedError

    @property
    @abstractmethod
    def gui(self) -> Any:
        """GUI Interface - Orchestrator Web Dashboard."""
        raise NotImplementedError

    @property
    @abstractmethod
    def console(self) -> BoardfarmPexpect:
        """Console Interface - On-prem CLI/SSH access."""
        raise NotImplementedError

    @abstractmethod
    def get_active_wan_interface(
        self, flow_dst: str | None = None, via: str = "console"
    ) -> str:
        """Return the logical WAN label currently forwarding traffic for a given flow.

        When the device uses PBR or per-application steering, different traffic may use
        different WAN interfaces (e.g. productivity via wan1, streaming via wan2).
        Use ``flow_dst`` to select which flow to inspect.

        - **flow_dst=None**: Returns the path for default/generic traffic. Implementations
          typically use a well-known destination (e.g. 8.8.8.8) to determine the default
          route. When PBR is in use, this may not reflect any specific application path.
        - **flow_dst="<ip>"**: Returns the WAN label used for traffic to that destination.
          Use the destination IP of the service under test (e.g. productivity server IP,
          streaming server IP) to assert the correct path for that application.

        The return value is ALWAYS a key from the inventory ``wan_interfaces`` mapping
        (e.g. ``"wan1"``, ``"wan2"``), never a physical OS interface name (e.g. ``"eth2"``
        or ``"GigabitEthernet0/0/0"``). This contract makes test code portable across
        device implementations where physical interface names differ between vendors.

        Implementations MUST:
        1. Query the device for its active forwarding interface (via CLI, API, or NBI).
        2. Reverse-look up the physical name in the ``wan_interfaces`` inventory mapping
           to obtain the logical label before returning.

        The ``wan_interfaces`` key is **required** in the device inventory config for all
        ``WANEdgeDevice`` implementations.

        :param flow_dst: Optional destination IP/prefix to select a specific flow.
            When None, returns the path for default traffic. When set (e.g. to a
            productivity or streaming server IP), returns the path for that flow.
        :param via: Interface to use ("console" for CLI, "nbi" for API, "gui" for web).
        :return: Logical WAN label, e.g. ``"wan1"`` or ``"wan2"``.
        :raises KeyError: if the physical interface returned by the device is absent from
            the ``wan_interfaces`` mapping.
        """
        raise NotImplementedError

    @abstractmethod
    def get_wan_path_metrics(self, via: str = "console") -> dict[str, PathMetrics]:
        """Return per-link quality metrics as measured by the device.

        :param via: Interface to use.
        :return: Mapping of logical WAN label → PathMetrics (keys match ``wan_interfaces``).
        """
        raise NotImplementedError

    @abstractmethod
    def get_wan_interface_status(self, via: str = "console") -> dict[str, LinkStatus]:
        """Return UP/DOWN/degraded state for each WAN interface.

        :param via: Interface to use.
        :return: Mapping of logical WAN label → LinkStatus (keys match ``wan_interfaces``).
        """
        raise NotImplementedError

    @abstractmethod
    def get_routing_table(self, via: str = "console") -> list[RouteEntry]:
        """Return the current forwarding/routing table.

        :param via: Interface to use.
        """
        raise NotImplementedError

    @abstractmethod
    def apply_policy(self, policy: dict, via: str = "nbi") -> None:
        """Apply a routing or SD-WAN policy (PBR rule, SLA threshold, etc.).

        :param policy: Vendor-neutral policy dict; device class translates to CLI/API.
        :param via: Interface to use (defaulting to API for policy changes).
        """
        raise NotImplementedError

    @abstractmethod
    def remove_policy(self, name: str, via: str = "nbi") -> None:
        """Remove a previously applied policy by name.

        Required for teardown: scenarios that apply policies must remove them so
        the next scenario starts from a clean baseline.

        :param name: Policy name (as recorded when applied, e.g. from policy dict).
        :param via: Interface to use.
        """
        raise NotImplementedError

    @abstractmethod
    def bring_wan_down(self, label: str, via: str = "console") -> None:
        """Bring a WAN interface down (e.g. cable unplug simulation).

        :param label: Logical WAN label (e.g. "wan1", "wan2").
        :param via: Interface to use.
        """
        raise NotImplementedError

    @abstractmethod
    def bring_wan_up(self, label: str, via: str = "console") -> None:
        """Bring a WAN interface up (restore after bring_wan_down).

        :param label: Logical WAN label (e.g. "wan1", "wan2").
        :param via: Interface to use.
        """
        raise NotImplementedError

    @abstractmethod
    def power_cycle(self) -> None:
        """Power cycle (reboot) the device.

        Implementation varies by platform:
        - **Hardware with PDU:** Control power supply (e.g. rpirdkb_cpe via get_pdu).
        - **Hardware with console:** Send reboot command via CLI (e.g. rpiprplos_cpe).
        - **Container:** Send reboot command via console; container exits and restarts
          (requires restart: always in docker-compose). E.g. LinuxSDWANRouter, vcpe_ofw.

        Callers (e.g. boardfarm_device_boot) use this to bring the device to a known
        state. Implementations must ensure the device is reachable again after the
        cycle (caller may retry connect or wait_for_hw_boot).
        """
        raise NotImplementedError

    @abstractmethod
    def get_telemetry(self, via: str = "nbi") -> dict:
        """Return a snapshot of device telemetry (uptime, session counts, CPU, etc.).

        :param via: Interface to use.
        """
        raise NotImplementedError

    @abstractmethod
    def get_security_log_events(self, since_s: int = 30) -> list[dict]:
        """Return security log entries recorded in the last ``since_s`` seconds.

        Each entry is a dict with at minimum:
          - "action"   : "block" | "alert" | "allow"
          - "src_ip"   : source IP address
          - "dst_port" : destination port (int)
          - "protocol" : "tcp" | "udp" | "icmp"
          - "timestamp": ISO-8601 string

        :param since_s: How far back to search (seconds from now).
        :return: List of event dicts; empty list if none found.
        """
        raise NotImplementedError
