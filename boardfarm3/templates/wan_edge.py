"""Boardfarm WAN Edge device template.

Harmonized abstract interface for SD-WAN appliances, derived from
cross-vendor API analysis of Cisco Catalyst SD-WAN, Fortinet FortiGate,
VMware VeloCloud, Palo Alto Prisma SD-WAN, and Cisco Meraki MX.

See: ``docs/cross-vendor sdwan API analysis.md``
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from boardfarm3.lib.boardfarm_pexpect import BoardfarmPexpect


# ── Dataclasses ───────────────────────────────────────────────────────


@dataclass
class PathMetrics:
    """Per-link quality metrics as measured by the device."""

    latency_ms: float
    jitter_ms: float
    loss_percent: float
    link_name: str
    mos: float | None = None


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


@dataclass
class SLAPolicy:
    """Quality thresholds for WAN link health monitoring.

    Declarative model aligned with commercial SD-WAN platforms:
    defining the policy activates monitoring; removing it deactivates.
    (Cisco SLA-class, Fortinet performance-sla, VeloCloud QoS profile,
    Prisma path-quality-profile, Meraki custom performance class.)
    """

    name: str
    max_latency_ms: float = 150.0
    max_jitter_ms: float = 30.0
    max_loss_percent: float = 10.0


@dataclass
class LinkHealthReport:
    """Current health metrics for a WAN link as reported by the
    appliance's SLA monitoring process."""

    state: str  # "up" | "down" | "degraded"
    route_installed: bool
    avg_rtt_ms: float | None
    jitter_ms: float | None
    loss_percent: float
    sla_compliant: bool
    mos: float | None = None


@dataclass
class AppFlow:
    """A single application-level traffic flow as identified by the
    device's DPI engine.

    Devices without DPI (e.g. LinuxSDWANRouter) return empty lists
    from :meth:`WANEdgeDevice.get_application_flows`.
    """

    application: str
    category: str
    src_ip: str
    dst_ip: str
    wan_interface: str
    bytes_sent: int
    bytes_received: int


@dataclass
class FirewallRule:
    """Vendor-neutral firewall rule definition.

    Supports both L3/L4 rules (protocol/cidr/port) and L7 rules
    (application name or category).  Set both ``application`` and
    ``application_category`` to ``None`` for L3/L4-only rules.

    When ``application_category`` is set (e.g. ``"Sports"``), the rule
    applies to all applications in that category.  When ``application``
    is set (e.g. ``"BitTorrent"``), the rule targets a specific app.

    Vendor mapping for L7:

    - **Meraki:** ``type: "applicationCategory"`` vs ``type: "application"``
    - **Cisco Catalyst:** NBAR2 app-family vs specific application
    - **FortiGate:** ``internet-service-group`` vs ``internet-service-id``
    - **VeloCloud:** Application category vs specific application
    - **Prisma:** App-ID group/category vs specific App-ID
    """

    name: str
    action: str  # "allow" | "deny" | "alert"
    protocol: str  # "tcp" | "udp" | "icmp" | "any"
    src_cidr: str  # CIDR notation or "any"
    dst_cidr: str  # CIDR notation or "any"
    dst_port: str  # "any", "443", "1-1024"
    application: str | None = None
    application_category: str | None = None
    log: bool = True


@dataclass
class VPNPeerStatus:
    """Status of a VPN/overlay tunnel to a peer site."""

    peer_id: str
    peer_name: str
    reachability: str  # "reachable" | "unreachable"
    uplink: str


@dataclass
class TrafficShapingRule:
    """A traffic shaping / QoS marking rule as read back from the device.

    Returned by :meth:`WANEdgeDevice.get_traffic_shaping_rules`.
    """

    name: str
    match: dict
    dscp_tag: int | None = None
    bandwidth_limit_kbps: int | None = None
    priority: str | None = None  # "low" | "normal" | "high"


# ── Template ──────────────────────────────────────────────────────────


class WANEdgeDevice(ABC):
    """Abstract interface for WAN Edge / SD-WAN appliances.

    Derived from cross-vendor API analysis covering Cisco Catalyst SD-WAN,
    Fortinet FortiGate, VMware VeloCloud, Palo Alto Prisma, and Meraki MX.

    Implementations: LinuxSDWANRouter, MerakiMXDevice, CiscoC8000DUT,
    FortiGateDUT, VelocloudDUT.
    """

    # ── Properties ────────────────────────────────────────────

    @property
    @abstractmethod
    def nbi(self) -> Any:
        """Northbound Interface — Orchestrator REST API client."""
        raise NotImplementedError

    @property
    @abstractmethod
    def gui(self) -> Any:
        """GUI Interface — Orchestrator Web Dashboard URL or driver."""
        raise NotImplementedError

    @property
    @abstractmethod
    def console(self) -> BoardfarmPexpect | None:
        """Console Interface — On-prem CLI/SSH access.

        Returns ``None`` for API-only devices (e.g. Meraki MX) that have
        no on-device CLI.  Callers should check for ``None`` before
        issuing console commands.
        """
        raise NotImplementedError

    # ── Monitoring ────────────────────────────────────────────

    @abstractmethod
    def get_active_wan_interface(
        self, flow_dst: str | None = None, via: str = "console"
    ) -> str:
        """Return the logical WAN label currently forwarding traffic for a given flow.

        When the device uses per-application steering, different traffic may
        use different WAN interfaces (e.g. productivity via wan1, streaming
        via wan2).  Use ``flow_dst`` to select which flow to inspect.

        - **flow_dst=None**: Returns the path for default/generic traffic.
        - **flow_dst="<ip>"**: Returns the WAN label for traffic to that destination.

        The return value is ALWAYS a key from the inventory ``wan_interfaces``
        mapping (e.g. ``"wan1"``, ``"wan2"``), never a physical OS interface
        name.

        :param flow_dst: Optional destination IP/prefix to select a specific flow.
        :param via: Interface to use ("console", "nbi", "gui").
        :return: Logical WAN label, e.g. ``"wan1"`` or ``"wan2"``.
        """
        raise NotImplementedError

    @abstractmethod
    def get_wan_path_metrics(self, via: str = "console") -> dict[str, PathMetrics]:
        """Return per-link quality metrics as measured by the device.

        :param via: Interface to use.
        :return: Mapping of logical WAN label -> PathMetrics.
        """
        raise NotImplementedError

    @abstractmethod
    def get_wan_interface_status(self, via: str = "console") -> dict[str, LinkStatus]:
        """Return UP/DOWN/degraded state for each WAN interface.

        :param via: Interface to use.
        :return: Mapping of logical WAN label -> LinkStatus.
        """
        raise NotImplementedError

    @abstractmethod
    def get_link_health(self, wan_label: str) -> LinkHealthReport:
        """Query current health metrics for a WAN link.

        Returns probe results from the appliance's SLA monitoring.

        :param wan_label: Logical WAN label (e.g. ``"wan1"``).
        :return: Current health report.
        """
        raise NotImplementedError

    @abstractmethod
    def get_telemetry(self, via: str = "nbi") -> dict:
        """Return a snapshot of device telemetry (uptime, CPU, memory, etc.).

        :param via: Interface to use.
        """
        raise NotImplementedError

    @abstractmethod
    def get_security_log_events(self, since_s: int = 30) -> list[dict]:
        """Return security log entries recorded in the last ``since_s`` seconds.

        This method covers **all** security-related events: firewall
        rule hits, content filter blocks, IPS/IDS alerts, and malware
        detections.  Implementations should normalise vendor-specific
        event formats into the common schema below.

        **Required fields** (every event dict must include):

          - ``"action"``    : ``"block"`` | ``"alert"`` | ``"allow"``
          - ``"src_ip"``    : source IP address
          - ``"dst_port"``  : destination port (int)
          - ``"protocol"``  : ``"tcp"`` | ``"udp"`` | ``"icmp"``
          - ``"timestamp"`` : ISO-8601 string

        **Optional fields** (include when the event type provides them):

          - ``"event_type"``            : ``"firewall"`` | ``"content_filter"``
            | ``"ips"`` | ``"malware"`` | ``"l7_firewall"``
          - ``"dst_ip"``               : destination IP address
          - ``"src_port"``             : source port (int)
          - ``"url"``                  : blocked/matched URL
            (content filter and URL-based events)
          - ``"category"``             : content filter or L7 category name
            (e.g. ``"Gambling"``, ``"Sports"``)
          - ``"application"``          : L7 application name
            (e.g. ``"BitTorrent"``)
          - ``"rule_name"``            : name of the firewall rule that
            matched (correlates with :attr:`FirewallRule.name`)
          - ``"signature"``            : IPS signature ID or name
          - ``"message"``              : human-readable event description

        Example — content filter block::

            {
                "action": "block",
                "event_type": "content_filter",
                "src_ip": "192.168.1.50",
                "dst_ip": "93.184.216.34",
                "dst_port": 443,
                "protocol": "tcp",
                "url": "https://www.example-gambling.com/slots",
                "category": "Gambling",
                "timestamp": "2026-03-12T14:30:00Z",
            }

        Example — L7 firewall block::

            {
                "action": "block",
                "event_type": "l7_firewall",
                "src_ip": "192.168.1.50",
                "dst_ip": "198.51.100.10",
                "dst_port": 6881,
                "protocol": "tcp",
                "application": "BitTorrent",
                "category": "Peer-to-peer",
                "rule_name": "block-p2p",
                "timestamp": "2026-03-12T14:31:00Z",
            }

        :param since_s: How far back to search (seconds from now).
        :return: List of event dicts; empty list if none found.
        """
        raise NotImplementedError

    # ── Application-layer (L7) monitoring ─────────────────────

    @abstractmethod
    def get_application_categories(self) -> list[dict]:
        """Return the device's known application category taxonomy.

        Each dict contains at minimum:
          - "id"       : vendor-specific category identifier
          - "name"     : human-readable category name (e.g. "Video Conferencing")

        Used to discover valid values for the ``application_category``
        match field in :meth:`apply_policy`.

        Devices without DPI (e.g. LinuxSDWANRouter) return ``[]``.
        """
        raise NotImplementedError

    @abstractmethod
    def get_application_flows(
        self, since_s: int = 60, app_filter: str | None = None
    ) -> list[AppFlow]:
        """Return application-level traffic flows identified by the device's DPI engine.

        :param since_s: How far back to search (seconds from now).
        :param app_filter: Optional application name or category to filter by.
            When ``None``, returns all observed flows.
        :return: List of :class:`AppFlow`; empty list if DPI is not available.
        """
        raise NotImplementedError

    # ── Optional monitoring (concrete defaults) ───────────────

    def get_routing_table(self, via: str = "console") -> list[RouteEntry]:
        """Return the current forwarding/routing table.

        Not all SD-WAN platforms expose this (e.g. Meraki MX has no
        routing table API).  The default implementation returns an empty
        list.  Override in implementations that support it.

        :param via: Interface to use.
        """
        return []

    def get_vpn_peer_status(self) -> list[VPNPeerStatus]:
        """Return VPN/overlay tunnel status for each peer site.

        Only relevant for multi-site topologies (e.g. Meraki AutoVPN,
        Cisco SD-WAN overlay, VeloCloud VPN mesh).  The default
        implementation returns an empty list.

        :return: List of :class:`VPNPeerStatus` for each peer.
        """
        return []

    def get_traffic_shaping_rules(self) -> list[TrafficShapingRule]:
        """Return currently configured traffic shaping / QoS marking rules.

        Each rule describes a match + action that the device applies to
        traffic (DSCP marking, bandwidth limiting, prioritisation).  This
        is a read-back mechanism to verify that rules applied via
        :meth:`apply_policy` (with ``set_dscp`` or similar actions) are
        in effect.

        Devices that do not expose their shaping rules via API return
        ``[]``.

        :return: List of :class:`TrafficShapingRule`.
        """
        return []

    # ── Configuration — traffic steering ──────────────────────

    @abstractmethod
    def apply_policy(self, policy: dict, via: str = "nbi") -> None:
        """Apply a traffic steering / SD-WAN policy.

        The policy dict is **vendor-neutral**; the device class translates
        it to the vendor's native API or CLI.

        **Policy dict schema:**

        .. code-block:: python

            {
                "name": "video-to-wan2",              # REQUIRED — used by remove_policy()
                "match": {                             # REQUIRED — traffic match criteria
                    "application_category": "...",     # L7 app category (primary for DPI devices)
                    "application": "...",              # L7 specific app name
                    "dst_prefix": "10.0.0.0/8",       # L3 destination CIDR
                    "src_prefix": "192.168.0.0/16",   # L3 source CIDR
                    "protocol": "tcp",                 # L3/L4 protocol
                    "dst_port": "443",                 # L4 destination port
                    "dscp": 34,                        # DSCP match (implementation-dependent)
                },
                "action": {                            # REQUIRED — steering and/or marking action
                    "prefer_wan": "wan2",              # logical WAN label
                    "load_balance": False,             # distribute across WANs
                    "set_dscp": 46,                    # mark matching packets with DSCP value (0-63)
                },
                "sla_policy": "voice-sla",             # optional: SLA policy reference
                "failover": "on_sla_violation",        # optional: "on_sla_violation" | "on_link_down"
            }

        The ``match`` dict supports multiple criteria simultaneously;
        the device class combines them with AND semantics.  At least one
        match criterion must be present.

        **Match fields by vendor support:**

        - ``application`` / ``application_category`` — all commercial platforms
        - ``dst_prefix`` / ``src_prefix`` — all platforms including LinuxSDWANRouter
        - ``protocol`` / ``dst_port`` — all platforms
        - ``dscp`` — LinuxSDWANRouter, FortiGate, Cisco; not Meraki

        **Action fields:**

        - ``prefer_wan`` — steer traffic to a specific WAN link
        - ``load_balance`` — distribute across available WANs
        - ``set_dscp`` — mark matching packets with a DSCP value (0-63).
          On Meraki: ``updateNetworkApplianceTrafficShapingRules`` with
          ``dscpTagValue``.  On Linux: ``iptables -j DSCP --set-dscp``.
          On FortiGate: ``set dscp-tag``.  On Cisco: policy-map ``set dscp``.

        At least one action field must be present.  ``set_dscp`` may be
        combined with ``prefer_wan`` (mark AND steer).

        Devices without DPI that receive an ``application`` or
        ``application_category`` match should log a warning and fall back
        to any L3/L4 match criteria present, or raise ``NotImplementedError``
        if no fallback is possible.

        :param policy: Vendor-neutral policy dict.
        :param via: Interface to use (default ``"nbi"`` for API).
        """
        raise NotImplementedError

    @abstractmethod
    def remove_policy(self, name: str, via: str = "nbi") -> None:
        """Remove a previously applied policy by name.

        Required for teardown: scenarios that apply policies must remove
        them so the next scenario starts from a clean baseline.

        :param name: Policy name as specified in the ``"name"`` field of the
            policy dict passed to :meth:`apply_policy`.
        :param via: Interface to use.
        """
        raise NotImplementedError

    # ── Configuration — SLA / performance monitoring ──────────

    @abstractmethod
    def configure_sla_policy(self, policy: SLAPolicy) -> None:
        """Define an SLA policy with quality thresholds.

        Uses a **declarative model** aligned with commercial SD-WAN
        platforms: defining the policy activates monitoring.  There is
        no separate start/stop lifecycle.

        Multiple policies may be defined; each is identified by
        :attr:`SLAPolicy.name`.

        Policies can be referenced by name in the ``sla_policy`` field
        of the :meth:`apply_policy` policy dict to tie steering decisions
        to SLA compliance.

        :param policy: SLA policy to define and activate.
        """
        raise NotImplementedError

    @abstractmethod
    def remove_sla_policy(self, name: str) -> None:
        """Remove a previously defined SLA policy.

        Deactivates monitoring for this policy.  Required for teardown.

        :param name: SLA policy name as specified in :attr:`SLAPolicy.name`.
        """
        raise NotImplementedError

    # ── Configuration — firewall rules ────────────────────────

    def get_firewall_rules(self) -> list[FirewallRule]:
        """Return currently configured firewall rules.

        Read-back mechanism to verify that rules applied via
        :meth:`apply_firewall_rule` are in effect.  Returns a list of
        :class:`FirewallRule` instances reflecting what the device has
        active.

        Vendor mapping:

        - **Meraki:** ``getNetworkApplianceFirewallL3FirewallRules`` +
          ``getNetworkApplianceFirewallL7FirewallRules``
        - **Cisco Catalyst:** ACL / security-policy read-back
        - **FortiGate:** ``GET /api/v2/cmdb/firewall/policy``
        - **VeloCloud:** Edge firewall rules via Orchestrator API
        - **Prisma:** ``GET /sdwan/v2.0/api/securitypolicyrules``
        - **LinuxSDWAN:** ``iptables -S`` — parse comment tags

        Devices that do not expose firewall rules return ``[]``.

        :return: List of :class:`FirewallRule`.
        """
        return []

    @abstractmethod
    def apply_firewall_rule(self, rule: FirewallRule, via: str = "nbi") -> None:
        """Apply a firewall rule (L3/L4 or L7 application-based).

        Distinct from :meth:`apply_policy`, which controls traffic
        **steering** (which WAN to use).  Firewall rules control traffic
        **admission** (allow / deny / alert).

        :param rule: Vendor-neutral firewall rule.
        :param via: Interface to use.
        """
        raise NotImplementedError

    @abstractmethod
    def remove_firewall_rule(self, name: str, via: str = "nbi") -> None:
        """Remove a previously applied firewall rule.

        Required for teardown.

        :param name: Firewall rule name as specified in :attr:`FirewallRule.name`.
        :param via: Interface to use.
        """
        raise NotImplementedError

    # ── Logging / syslog (concrete defaults — optional) ─────────

    def configure_syslog(
        self,
        server: str,
        port: int = 514,
        roles: list[str] | None = None,
    ) -> None:
        """Configure remote syslog server destination and event categories.

        Vendor-neutral ``roles`` specify which event categories to forward.
        Common role names:

        - ``"firewall"``   — firewall allow/deny events
        - ``"flows"``      — traffic flow summaries
        - ``"security"``   — IPS / malware / threat events
        - ``"urls"``       — URL / content filter events
        - ``"event_log"``  — general appliance events

        Each device class translates these to the vendor-specific category
        names.  If ``roles`` is ``None``, the implementation should forward
        all available categories.

        Vendor mapping:

        - **Meraki:** ``updateNetworkSyslogServers(servers=[{host, port, roles}])``
        - **Cisco Catalyst:** ``logging`` feature template — server, facility
        - **FortiGate:** ``PUT /api/v2/cmdb/log.syslogd/setting`` + filter
        - **VeloCloud:** Edge/profile syslog export config
        - **Prisma:** Syslog server profile + log forwarding profile
        - **LinuxSDWAN:** rsyslog remote forward rule

        Devices that do not support syslog configuration inherit the
        default no-op.

        :param server: Syslog server IP address or hostname.
        :param port: Syslog server port (default 514).
        :param roles: Event categories to forward; ``None`` = all.
        """

    def get_syslog_settings(self) -> dict:
        """Return current syslog configuration.

        Returns a dict with at minimum:

        - ``"servers"``: list of dicts, each with ``"host"``, ``"port"``,
          and ``"roles"`` (list of category names being forwarded)

        Example return value::

            {
                "servers": [
                    {
                        "host": "10.1.1.100",
                        "port": 514,
                        "roles": ["firewall", "flows", "security"]
                    }
                ]
            }

        Devices without syslog configuration return ``{}``.
        """
        return {}

    # ── Security services (concrete defaults — optional) ───────

    def configure_ips(
        self,
        mode: str = "prevention",
        ruleset: str = "balanced",
    ) -> None:
        """Configure Intrusion Detection / Prevention System (IDS/IPS).

        Vendor-neutral modes:

        - ``"disabled"``   — IPS/IDS is off
        - ``"detection"``  — IDS only: alert on threats but do not block
        - ``"prevention"`` — IPS: actively block detected threats

        Vendor-neutral ruleset sensitivity (permissive → strict):

        - ``"connectivity"`` — minimise false positives; only high-confidence signatures
        - ``"balanced"``     — recommended default; balance detection vs. false positives
        - ``"security"``     — maximum coverage; may increase false positives

        Devices without IPS (e.g. LinuxSDWANRouter) inherit the default
        no-op.  Override in implementations that support IPS.

        :param mode: ``"disabled"`` | ``"detection"`` | ``"prevention"``
        :param ruleset: ``"connectivity"`` | ``"balanced"`` | ``"security"``
        """

    def get_ips_settings(self) -> dict:
        """Return current IPS configuration.

        Returns a dict with at minimum:

        - ``"mode"``: ``"disabled"`` | ``"detection"`` | ``"prevention"``
        - ``"ruleset"``: ``"connectivity"`` | ``"balanced"`` | ``"security"``

        Devices without IPS return ``{}``.
        """
        return {}

    def configure_malware_protection(self, enabled: bool = True) -> None:
        """Enable or disable malware / AMP protection.

        Vendor-neutral: ``True`` enables the vendor's malware engine,
        ``False`` disables it.

        Vendor mapping:

        - **Meraki:** ``updateNetworkApplianceSecurityMalware(mode="enabled"/"disabled")``
        - **Cisco Catalyst:** AMP feature template toggle
        - **FortiGate:** AV profile enable/disable
        - **Prisma:** WildFire integration toggle
        - **LinuxSDWANRouter:** no-op (no malware engine)

        :param enabled: ``True`` to enable, ``False`` to disable.
        """

    def get_malware_settings(self) -> dict:
        """Return current malware protection configuration.

        Returns a dict with at minimum:

        - ``"enabled"``: ``True`` | ``False``

        Devices without malware protection return ``{}``.
        """
        return {}

    def configure_content_filter(
        self,
        enabled: bool = True,
        blocked_categories: list[str] | None = None,
        allowed_urls: list[str] | None = None,
        blocked_urls: list[str] | None = None,
    ) -> None:
        """Configure URL / content filtering.

        :param enabled: ``True`` to enable, ``False`` to disable.
        :param blocked_categories: URL categories to block
            (e.g. ``["Adult Content", "Gambling"]``).
        :param allowed_urls: URLs to always allow (whitelist).
        :param blocked_urls: URLs to always block (blacklist).
        """

    def get_content_filter_settings(self) -> dict:
        """Return current content filtering configuration.

        Returns a dict with at minimum:

        - ``"enabled"``: ``True`` | ``False``
        - ``"blocked_categories"``: list of blocked category names
        - ``"allowed_urls"``: list of whitelisted URLs
        - ``"blocked_urls"``: list of blacklisted URLs

        Devices without content filtering return ``{}``.
        """
        return {}

    # ── Interface control ─────────────────────────────────────

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
        - **Hardware with PDU:** Control power supply.
        - **Hardware with console:** Send reboot command via CLI.
        - **Container:** Send reboot command; container restarts.
        - **API-only:** Call device reboot API endpoint.
        """
        raise NotImplementedError
