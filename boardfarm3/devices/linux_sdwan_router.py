"""Boardfarm Linux SD-WAN Router device module."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
from argparse import Namespace
from pathlib import Path
from time import sleep
from typing import TYPE_CHECKING, Any

import jc.parsers.ping

from boardfarm3 import hookimpl
from boardfarm3.devices.base_devices.linux_device import LinuxDevice
from boardfarm3.exceptions import DeviceBootFailure, DeviceConnectionError
from boardfarm3.lib.connection_factory import connection_factory
from boardfarm3.templates.wan_edge import (
    AppFlow,
    FirewallRule,
    LinkHealthReport,
    LinkStatus,
    PathMetrics,
    RouteEntry,
    SLAPolicy,
    TrafficShapingRule,
    WANEdgeDevice,
)

if TYPE_CHECKING:
    from boardfarm3.lib.boardfarm_pexpect import BoardfarmPexpect
    from boardfarm3.lib.device_manager import DeviceManager

_LOGGER = logging.getLogger(__name__)

# Shell prompts: bash (root@host:path#) and minimal (#)
LINUX_SDWAN_SHELL_PROMPTS = [
    r"[\w\-]+@[\w\-]+:[\w/~]+#",  # bash: root@sdwan-router:~#
    r"#\s*",  # minimal root prompt
]


class LinuxSDWANRouter(LinuxDevice, WANEdgeDevice):
    """Boardfarm Linux SD-WAN Router device.

    Implements WANEdgeDevice using FRR and Linux kernel networking.
    Supports both SSH (authenticated_ssh) and docker exec (local_cmd) connections.
    """

    def __init__(self, config: dict, cmdline_args: Namespace) -> None:
        """Initialize Linux SD-WAN Router device.

        :param config: device configuration (must include wan_interfaces, lan_interface)
        :param cmdline_args: command line arguments
        """
        super().__init__(config, cmdline_args)
        self._wan_interfaces: dict[str, str] = config.get("wan_interfaces", {})
        if not self._wan_interfaces:
            raise ValueError(
                "wan_interfaces is required for LinuxSDWANRouter. "
                "Example: {\"wan1\": \"eth-wan1\", \"wan2\": \"eth-wan2\"}"
            )
        self._physical_to_logical: dict[str, str] = {
            v: k for k, v in self._wan_interfaces.items()
        }
        self._lan_interface: str = config.get("lan_interface", "eth-lan")
        self._flow_src: str = config.get("flow_src", "192.168.10.10")
        self._wan_gateways: dict[str, str] = config.get("wan_gateways", {})
        if not self._wan_gateways:
            _LOGGER.warning(
                "wan_gateways not configured; get_wan_path_metrics and apply_policy "
                "may not work correctly. Example: {\"wan1\": \"10.10.1.2\", \"wan2\": \"10.10.2.2\"}"
            )
        # wan_metrics maps WAN label → kernel metric (lower = higher priority).
        self._wan_metrics: dict[str, int] = config.get("wan_metrics", {})
        self._sla_policies: dict[str, SLAPolicy] = {}
        self._sla_bindings: dict[str, str] = {}
        self._sla_monitoring_active: bool = False

    def _to_logical(self, physical: str) -> str:
        """Translate a physical interface name to its logical WAN label."""
        try:
            return self._physical_to_logical[physical]
        except KeyError as exc:
            raise KeyError(
                f"Physical interface {physical!r} not found in wan_interfaces "
                f"config {self._wan_interfaces}"
            ) from exc

    @staticmethod
    def _extract_json(output: str) -> str:
        """Extract JSON array or object from output that may include command echo.

        Console output often echoes the command before the JSON. This finds the
        first '[' or '{' and returns the complete JSON value.
        """
        output = output.strip()
        for start_char, end_char in (("[", "]"), ("{", "}")):
            idx = output.find(start_char)
            if idx >= 0:
                depth = 0
                for i in range(idx, len(output)):
                    if output[i] == start_char:
                        depth += 1
                    elif output[i] == end_char:
                        depth -= 1
                        if depth == 0:
                            return output[idx : i + 1]
        return output

    def _connect(self) -> None:
        """Establish connection via SSH, docker exec (local_cmd), or docker_exec."""
        if self._console is not None:
            return
        conn_type = self._config.get("connection_type", "authenticated_ssh")

        if conn_type in ("local_cmd", "docker_exec"):
            if conn_type == "docker_exec":
                container = self._config.get("container_name", "linux-sdwan-router")
                conn_cmd = [f"docker exec -i {container} bash -i"]
            else:
                conn_cmd = self._config.get("conn_cmd", [])
            if not conn_cmd:
                raise ValueError(
                    "conn_cmd or (docker_exec + container_name) is required. "
                    "Example: conn_cmd [\"docker exec -it linux-sdwan-router sh\"] "
                    "or connection_type docker_exec with container_name"
                )
            self._console = connection_factory(
                connection_type="local_cmd",
                connection_name=f"{self.device_name}.console",
                conn_command=conn_cmd[0],
                save_console_logs=getattr(
                    self._cmdline_args, "save_console_logs", ""
                ),
                shell_prompt=LINUX_SDWAN_SHELL_PROMPTS,
            )
            self._console.login_to_server()
        else:
            super()._connect()
        self._console.execute_command(
            "stty columns 400 2>/dev/null; export TERM=xterm 2>/dev/null || true"
        )

    async def _connect_async(self) -> None:
        """Establish connection (async) — delegates to sync _connect."""
        self._connect()

    @property
    def nbi(self) -> Any:
        """Northbound Interface - Linux Router has no REST API."""
        return None

    @property
    def gui(self) -> Any:
        """GUI Interface - Linux Router has no web dashboard."""
        return None

    @property
    def console(self) -> BoardfarmPexpect | None:
        """Return console for CLI access."""
        return self._console

    def get_active_wan_interface(
        self, flow_dst: str | None = None, via: str = "console"
    ) -> str:
        """Return the logical WAN label currently forwarding traffic.

        When flow_dst is set, simulates LAN-originated traffic (from flow_src via
        lan_interface) so PBR policies that match on ingress are applied.
        """
        dst = flow_dst or "8.8.8.8"
        if flow_dst:
            cmd = (
                f"ip -o route get {dst} from {self._flow_src} iif {self._lan_interface}"
            )
        else:
            cmd = f"ip -o route get {dst}"

        for attempt in range(3):
            output = self._console.execute_command(cmd)
            if "Network is unreachable" in output:
                raise ValueError(
                    f"No route to {dst} (Network is unreachable). "
                    "FRR may not have installed routes yet; ensure boot completed."
                )
            match = re.search(r"dev\s+(\S+)", output)
            if match:
                physical = match.group(1)
                return self._to_logical(physical)
            _LOGGER.debug(
                "ip route get parse miss (attempt %d/3): %r", attempt + 1, output,
            )
            sleep(0.05)

        raise ValueError(f"Could not parse output from 'ip route get {dst}': {output}")

    def get_wan_path_metrics(self, via: str = "console") -> dict[str, PathMetrics]:
        """Return per-link quality metrics via ping probes."""
        result: dict[str, PathMetrics] = {}
        for label, gateway in self._wan_gateways.items():
            if label not in self._wan_interfaces:
                continue
            physical = self._wan_interfaces[label]
            output = self._console.execute_command(
                f"ping -c 5 -i 0.2 {gateway} 2>/dev/null || echo '100% packet loss'"
            )
            # Strip pexpect command-echo: jc expects output starting at "PING "
            ping_start = output.find("PING ")
            if ping_start > 0:
                output = output[ping_start:]
            try:
                parsed = jc.parsers.ping.parse(output)
            except Exception:
                result[label] = PathMetrics(
                    latency_ms=0.0,
                    jitter_ms=0.0,
                    loss_percent=100.0,
                    link_name=physical,
                )
                continue
            if isinstance(parsed, list):
                parsed = parsed[0] if parsed else {}
            rtt = (
                parsed.get("round_trip_ms_avg")
                or parsed.get("rtt_avg_ms")
                or parsed.get("round_trip_avg_ms")
                or 0.0
            )
            mdev = (
                parsed.get("round_trip_ms_stddev")
                or parsed.get("rtt_mdev_ms")
                or 0.0
            )
            # Use explicit None check — 0% loss is falsy and must not be replaced
            loss_val = parsed.get("packet_loss_percent")
            loss = 100.0 if loss_val is None else loss_val
            result[label] = PathMetrics(
                latency_ms=float(rtt),
                jitter_ms=float(mdev),
                loss_percent=float(loss),
                link_name=physical,
            )
        return result

    def get_wan_interface_status(self, via: str = "console") -> dict[str, LinkStatus]:
        """Return UP/DOWN state for each WAN interface."""
        output = self._console.execute_command("ip -j link show")
        try:
            links = json.loads(self._extract_json(output))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Could not parse 'ip -j link show' output: {output}") from exc
        result: dict[str, LinkStatus] = {}
        physical_names = set(self._wan_interfaces.values())
        for link in links:
            iface = link.get("ifname", "")
            if iface not in physical_names:
                continue
            operstate = (link.get("operstate") or "unknown").lower()
            state = "up" if operstate == "unknown" or operstate == "up" else "down"
            addrs = link.get("addr_info", [])
            ip_addr = ""
            for addr in addrs:
                if addr.get("family") == "inet":
                    ip_addr = addr.get("local", "")
                    break
            label = self._to_logical(iface)
            result[label] = LinkStatus(name=iface, state=state, ip_address=ip_addr)
        return result

    def get_routing_table(self, via: str = "console") -> list[RouteEntry]:
        """Return the current forwarding table."""
        output = self._console.execute_command("ip -j route show")
        try:
            routes = json.loads(self._extract_json(output))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Could not parse 'ip -j route show' output: {output}"
            ) from exc
        result: list[RouteEntry] = []
        for r in routes:
            dst = r.get("dst", "0.0.0.0/0")
            if dst == "default":
                dst = "0.0.0.0/0"
            gw = r.get("gateway", "")
            dev = r.get("dev", "")
            metric = int(r.get("metric", 0))
            result.append(
                RouteEntry(
                    destination=dst,
                    gateway=gw,
                    interface=dev,
                    metric=metric,
                )
            )
        return result

    def get_traffic_shaping_rules(self) -> list[TrafficShapingRule]:
        """Read back DSCP marking rules from iptables mangle table."""
        output = self._console.execute_command(
            "iptables -t mangle -S POSTROUTING 2>/dev/null || true"
        )
        rules: list[TrafficShapingRule] = []
        for line in output.strip().splitlines():
            if "bf_" not in line or "_dscp" not in line:
                continue
            name_match = re.search(r'"bf_(.+?)_dscp"', line)
            dscp_match = re.search(r"--set-dscp\s+(\d+)", line)
            if not name_match or not dscp_match:
                continue
            match_dict: dict[str, str] = {}
            dst_match = re.search(r"-d\s+(\S+)", line)
            src_match = re.search(r"-s\s+(\S+)", line)
            proto_match = re.search(r"-p\s+(\S+)", line)
            dport_match = re.search(r"--dport\s+(\S+)", line)
            if dst_match:
                match_dict["dst_prefix"] = dst_match.group(1)
            if src_match:
                match_dict["src_prefix"] = src_match.group(1)
            if proto_match:
                match_dict["protocol"] = proto_match.group(1)
            if dport_match:
                match_dict["dst_port"] = dport_match.group(1)
            rules.append(TrafficShapingRule(
                name=name_match.group(1),
                match=match_dict,
                dscp_tag=int(dscp_match.group(1)),
            ))
        return rules

    def _run_vtysh(self, cmds: list[str]) -> None:
        """Run FRR vtysh commands via temp file on device.

        Uses host tempfile + docker cp when connected to a container,
        otherwise creates the file on the device via cat heredoc.
        """
        vtysh_input = "\n".join(cmds)
        path = "/tmp/vtysh_bf_cfg"
        container = self._get_container_name()
        if container:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".vtysh", delete=False
            ) as f:
                f.write(vtysh_input)
                f.flush()
                host_path = f.name
            try:
                subprocess.run(
                    ["docker", "cp", host_path, f"{container}:{path}"],
                    check=True,
                )
                self._console.execute_command(f"vtysh < {path}")
            finally:
                self._console.execute_command(f"rm -f {path}")
                Path(host_path).unlink(missing_ok=True)
        else:
            self._console.execute_command(
                f"cat > {path} << 'VTYSH_EOF'\n{vtysh_input}\nVTYSH_EOF"
            )
            try:
                self._console.execute_command(f"vtysh < {path}")
            finally:
                self._console.execute_command(f"rm -f {path}")

    def apply_policy(self, policy: dict, via: str = "nbi") -> None:
        """Apply PBR policy via FRR pbr-map, and optionally DSCP marking via iptables."""
        name = policy.get("name", "pbr-policy")
        match_cfg = policy.get("match", {})
        action_cfg = policy.get("action", {})
        prefer_wan = action_cfg.get("prefer_wan")
        set_dscp = action_cfg.get("set_dscp")

        if not prefer_wan and set_dscp is None:
            raise ValueError(
                "policy.action must contain at least 'prefer_wan' or 'set_dscp'"
            )

        dst_prefix = match_cfg.get("dst_prefix", "0.0.0.0/0")
        if dst_prefix == "any":
            dst_prefix = "0.0.0.0/0"

        if prefer_wan:
            gateway = self._wan_gateways.get(prefer_wan)
            if not gateway:
                raise ValueError(
                    f"wan_gateways[{prefer_wan!r}] not configured; cannot apply policy"
                )
            cmds = [
                "configure terminal",
                f"no pbr-map {name}",
                f"pbr-map {name} seq 10",
                f" match dst-ip {dst_prefix}",
                f" set nexthop {gateway}",
                " exit",
                f"interface {self._lan_interface}",
                f" no pbr-policy",
                f" pbr-policy {name}",
                " exit",
                "exit",
            ]
            self._run_vtysh(cmds)

        if set_dscp is not None:
            self._apply_dscp_marking(name, match_cfg, int(set_dscp))

    def _apply_dscp_marking(
        self, name: str, match_cfg: dict, dscp_value: int
    ) -> None:
        """Apply DSCP marking via iptables mangle table."""
        ipt_match = self._build_iptables_match(match_cfg)
        self._console.execute_command(
            f"iptables -t mangle -A POSTROUTING {ipt_match} "
            f"-j DSCP --set-dscp {dscp_value} "
            f'-m comment --comment "bf_{name}_dscp"'
        )

    def _build_iptables_match(self, match_cfg: dict) -> str:
        """Build iptables match flags from a policy match dict."""
        parts: list[str] = []
        if match_cfg.get("protocol") and match_cfg["protocol"] != "any":
            parts.append(f"-p {match_cfg['protocol']}")
        if match_cfg.get("src_prefix") and match_cfg["src_prefix"] != "any":
            parts.append(f"-s {match_cfg['src_prefix']}")
        if match_cfg.get("dst_prefix") and match_cfg["dst_prefix"] != "any":
            dst = match_cfg["dst_prefix"]
            if dst == "0.0.0.0/0":
                pass
            else:
                parts.append(f"-d {dst}")
        if match_cfg.get("dst_port") and match_cfg["dst_port"] != "any":
            proto = match_cfg.get("protocol", "tcp")
            if proto in ("tcp", "udp"):
                parts.append(f"--dport {match_cfg['dst_port']}")
        if match_cfg.get("dscp") is not None:
            parts.append(f"-m dscp --dscp {match_cfg['dscp']}")
        return " ".join(parts)

    def remove_policy(self, name: str, via: str = "nbi") -> None:
        """Remove PBR policy via FRR vtysh and any DSCP mangle rules."""
        cmds = [
            "configure terminal",
            f"interface {self._lan_interface}",
            " no pbr-policy",
            " exit",
            f"no pbr-map {name}",
            "exit",
        ]
        self._run_vtysh(cmds)
        self._console.execute_command(
            f'iptables -t mangle -S POSTROUTING | grep "bf_{name}_dscp" | '
            f"sed 's/-A/-D/' | while read rule; do iptables -t mangle $rule; done"
        )

    def bring_wan_down(self, label: str, via: str = "console") -> None:
        """Bring a WAN interface down."""
        physical = self._wan_interfaces.get(label)
        if not physical:
            raise KeyError(f"Unknown WAN label {label!r}")
        self._console.execute_command(f"ip link set {physical} down")

    def bring_wan_up(self, label: str, via: str = "console") -> None:
        """Bring a WAN interface up.

        The SLA probe daemon will detect the gateway is reachable again
        and re-install the FRR static route once the recovery threshold
        is met.
        """
        physical = self._wan_interfaces.get(label)
        if not physical:
            raise KeyError(f"Unknown WAN label {label!r}")
        self._console.execute_command(f"ip link set {physical} up")
        _LOGGER.debug(
            "%s bring_wan_up(%r): interface %s set up, "
            "SLA probe will re-install route on recovery",
            self.device_name, label, physical,
        )

    def _get_container_name(self) -> str | None:
        """Extract container name from config for docker exec / local_cmd."""
        name = self._config.get("container_name")
        if name:
            return name
        conn_cmd = self._config.get("conn_cmd", [])
        if not conn_cmd:
            return None
        # Parse "docker exec -i CONTAINER ..." or "docker exec CONTAINER ..."
        parts = conn_cmd[0].split()
        if "exec" not in parts:
            return None
        idx = parts.index("exec") + 1
        while idx < len(parts) and parts[idx].startswith("-"):
            idx += 1
        return parts[idx] if idx < len(parts) else None

    def power_cycle(self) -> None:
        """Power cycle (reboot) the device.

        For local_cmd/docker_exec: runs `docker restart <container>` from the host.
        This reliably restarts the container regardless of init or available commands.
        Disconnects, then retries _connect until success or timeout.
        """
        container = self._get_container_name()
        if container:
            _LOGGER.info("Restarting container %s via docker restart", container)
            self._disconnect()
            subprocess.run(["docker", "restart", container], check=True)
        else:
            raise DeviceBootFailure(
                "Cannot power cycle: no container_name or conn_cmd with docker exec "
                "in config. Add container_name or conn_cmd for local_cmd connection."
            )
        timeout_s = 120
        interval_s = 3
        elapsed = 0
        last_exc = None
        while elapsed < timeout_s:
            sleep(interval_s)
            elapsed += interval_s
            try:
                self._connect()
                _LOGGER.info("Reconnected to %s after reboot", self.device_name)
                return
            except (DeviceConnectionError, OSError, ValueError) as exc:
                last_exc = exc
                _LOGGER.debug("Reconnect attempt failed (%ds/%ds): %s", elapsed, timeout_s, exc)
        msg = f"Failed to reconnect to {self.device_name} within {timeout_s}s after reboot"
        raise DeviceBootFailure(msg) from last_exc

    def _wait_for_interfaces(self, timeout_s: int = 60) -> None:
        """Wait until eth-lan, eth-wan1, eth-wan2 are present via ip -o link show."""
        required = {self._lan_interface} | set(self._wan_interfaces.values())
        elapsed = 0
        interval_s = 2
        while elapsed < timeout_s:
            out = self._console.execute_command("ip -o link show")
            present = set()
            for line in out.strip().splitlines():
                if ": " in line:
                    parts = line.split(": ", 2)
                    if len(parts) >= 2:
                        present.add(parts[1].split("@")[0])
            if required <= present:
                _LOGGER.info("Interfaces %s ready on %s", sorted(required), self.device_name)
                return
            sleep(interval_s)
            elapsed += interval_s
        msg = f"Interfaces {sorted(required)} not ready on {self.device_name} within {timeout_s}s"
        raise DeviceBootFailure(msg)

    def _install_default_routes(self) -> None:
        """Install FRR static default routes from wan_gateways / wan_metrics config.

        Routes are installed via ``vtysh`` so FRR's ``staticd`` owns them.
        The SLA probe daemon (:meth:`start_sla_monitoring`) controls these
        routes at runtime: withdrawing them when a link breaches SLA
        thresholds, and re-installing them on recovery.

        Idempotent — FRR silently ignores duplicate static routes.

        :raises DeviceBootFailure: if wan_gateways is not configured.
        """
        if not self._wan_gateways:
            raise DeviceBootFailure(
                f"Cannot install default routes on {self.device_name}: "
                "wan_gateways not configured in inventory config"
            )
        cmds = ["configure terminal"]
        for label, gateway in self._wan_gateways.items():
            if label not in self._wan_interfaces:
                continue
            metric = self._wan_metrics.get(label)
            route_cmd = f"ip route 0.0.0.0/0 {gateway}"
            if metric is not None:
                route_cmd += f" {metric}"
            cmds.append(route_cmd)
            _LOGGER.info(
                "Installing FRR static route on %s: %s",
                self.device_name, route_cmd,
            )
        cmds.append("exit")
        self._run_vtysh(cmds)

    def _wait_for_frr(self, timeout_s: int = 45) -> None:
        """Wait for FRR control plane, then install and verify default routes.

        Three preconditions are polled until satisfied:

        1. **Connected routes** — ``ip route show`` lists at least one route
           per WAN interface (confirms Raikou interfaces have IPs).
        2. **FRR control plane** — ``vtysh -c "show version"`` succeeds
           (confirms FRR daemons are ready for PBR policy commands).
        3. **mgmtd** — ``pgrep -x mgmtd`` succeeds.  FRR 10.x routes
           static-route configuration through mgmtd; without it, ``ip route``
           commands via vtysh silently fail with "mgmtd is not running".

        Once all three are met, default routes are installed via
        :meth:`_install_default_routes` using the wan_gateways and wan_metrics
        from the boardfarm inventory config, and a final verification confirms
        the ``default`` entry is present in the kernel routing table.
        """
        wan_devs = set(self._wan_interfaces.values())
        elapsed = 0
        interval_s = 2
        routes_ok = False
        vtysh_ok = False
        mgmtd_ok = False
        while elapsed < timeout_s:
            if not routes_ok:
                route_out = self._console.execute_command("ip route show 2>/dev/null || true")
                routes_ok = all(f"dev {dev}" in route_out for dev in wan_devs)

            if not vtysh_ok:
                vtysh_out = self._console.execute_command(
                    "vtysh -c 'show version' 2>&1 || true"
                )
                vtysh_ok = (
                    "FRRouting" in vtysh_out
                    and "Cannot connect" not in vtysh_out
                    and "Failed to connect" not in vtysh_out
                )

            if not mgmtd_ok:
                mgmtd_out = self._console.execute_command(
                    "pgrep -x mgmtd >/dev/null 2>&1 && echo MGMTD_READY || echo MGMTD_MISSING"
                )
                mgmtd_ok = "MGMTD_READY" in mgmtd_out

            if routes_ok and vtysh_ok and mgmtd_ok:
                break

            _LOGGER.debug(
                "%s waiting for FRR: routes_ok=%s vtysh_ok=%s mgmtd_ok=%s (elapsed=%ds)",
                self.device_name, routes_ok, vtysh_ok, mgmtd_ok, elapsed,
            )
            sleep(interval_s)
            elapsed += interval_s
        else:
            missing = []
            if not routes_ok:
                missing.append("kernel routes on WAN interfaces")
            if not vtysh_ok:
                missing.append("vtysh connectivity")
            if not mgmtd_ok:
                missing.append("mgmtd daemon")
            raise DeviceBootFailure(
                f"FRR not ready on {self.device_name} within {timeout_s}s: "
                f"{' and '.join(missing)} not available"
            )

        self._install_default_routes()

        route_out = self._console.execute_command("ip route show 2>/dev/null || true")
        if "default" not in route_out:
            raise DeviceBootFailure(
                f"Default routes failed to install on {self.device_name}. "
                f"Route table after install:\n{route_out}"
            )
        _LOGGER.info(
            "FRR ready on %s (connected routes: %s, default routes: installed, vtysh: OK)",
            self.device_name,
            sorted(wan_devs),
        )

    def get_telemetry(self, via: str = "nbi") -> dict:
        """Return device telemetry (uptime, CPU, memory).

        Uses regex extraction so that pexpect command-echo in the output does
        not cause silent parse failures.
        """
        result: dict[str, Any] = {}
        try:
            uptime_out = self._console.execute_command("cat /proc/uptime")
            # /proc/uptime: "<uptime_sec> <idle_sec>" — find the first float
            m = re.search(r"(\d+\.\d+)\s+\d+\.\d+", uptime_out)
            result["uptime_seconds"] = float(m.group(1)) if m else 0.0
        except Exception:
            result["uptime_seconds"] = 0.0
        try:
            stat_out = self._console.execute_command("cat /proc/stat")
            for line in stat_out.splitlines():
                if line.startswith("cpu "):
                    fields = line.split()
                    if len(fields) >= 5:
                        user, nice, sys, idle = (
                            float(fields[1]),
                            float(fields[2]),
                            float(fields[3]),
                            float(fields[4]),
                        )
                        total = user + nice + sys + idle
                        result["cpu_load_percent"] = (
                            (user + nice + sys) / total * 100 if total > 0 else 0
                        )
                    break
        except Exception:
            result["cpu_load_percent"] = 0.0
        try:
            mem_out = self._console.execute_command("cat /proc/meminfo")
            mem_total = mem_avail = 0
            for line in mem_out.splitlines():
                if line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    mem_avail = int(line.split()[1])
            result["mem_used_percent"] = (
                (1 - mem_avail / mem_total) * 100 if mem_total > 0 else 0
            )
        except Exception:
            result["mem_used_percent"] = 0.0
        return result

    def get_security_log_events(self, since_s: int = 30) -> list[dict]:
        """Return security log entries (iptables LOG, journalctl)."""
        events: list[dict] = []
        try:
            out = self._console.execute_command(
                f"journalctl -u iptables --since '{since_s}s ago' "
                "--no-pager -o json 2>/dev/null || true"
            )
            for line in out.strip().splitlines():
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    msg = entry.get("MESSAGE", "")
                    if "DROP" in msg or "REJECT" in msg:
                        events.append(
                            {
                                "action": "block",
                                "src_ip": "",
                                "dst_port": 0,
                                "protocol": "tcp",
                                "timestamp": entry.get("__REALTIME_TIMESTAMP", ""),
                            }
                        )
                except json.JSONDecodeError:
                    pass
        except Exception:
            pass
        return events

    # ── Application-layer (L7) ───────────────────────────────────

    def get_application_categories(self) -> list[dict]:
        """LinuxSDWANRouter has no DPI engine."""
        return []

    def get_application_flows(
        self, since_s: int = 60, app_filter: str | None = None
    ) -> list[AppFlow]:
        """LinuxSDWANRouter has no DPI engine."""
        return []

    # ── Syslog ─────────────────────────────────────────────────

    def configure_syslog(
        self,
        server: str,
        port: int = 514,
        roles: list[str] | None = None,
    ) -> None:
        """Configure rsyslog remote forwarding."""
        self._console.execute_command(
            f'echo "*.* @{server}:{port}" > /etc/rsyslog.d/50-boardfarm.conf'
        )
        self._console.execute_command(
            "systemctl restart rsyslog 2>/dev/null "
            "|| service rsyslog restart 2>/dev/null || true"
        )
        self._syslog_server = server
        self._syslog_port = port
        self._syslog_roles = roles or ["firewall", "flows", "security"]
        _LOGGER.info(
            "%s: syslog configured → %s:%d (roles=%s)",
            self.device_name, server, port, self._syslog_roles,
        )

    def get_syslog_settings(self) -> dict:
        """Read back current rsyslog remote forwarding config."""
        server = getattr(self, "_syslog_server", None)
        if not server:
            return {}
        return {
            "servers": [
                {
                    "host": self._syslog_server,
                    "port": getattr(self, "_syslog_port", 514),
                    "roles": getattr(
                        self, "_syslog_roles",
                        ["firewall", "flows", "security"],
                    ),
                }
            ]
        }

    # ── Firewall rules ────────────────────────────────────────

    def get_firewall_rules(self) -> list[FirewallRule]:
        """Read back boardfarm-managed iptables rules."""
        rules: list[FirewallRule] = []
        for chain in ("INPUT", "FORWARD"):
            output = self._console.execute_command(
                f"iptables -S {chain} 2>/dev/null || true"
            )
            for line in output.strip().splitlines():
                if "bf_" not in line:
                    continue
                name_match = re.search(r'"bf_(.+?)"', line)
                if not name_match:
                    continue
                name = name_match.group(1)
                target_match = re.search(r"-j\s+(ACCEPT|DROP|LOG)", line)
                target = target_match.group(1) if target_match else "DROP"
                action_map = {"ACCEPT": "allow", "DROP": "deny", "LOG": "alert"}
                proto_match = re.search(r"-p\s+(\S+)", line)
                src_match = re.search(r"-s\s+(\S+)", line)
                dst_match = re.search(r"-d\s+(\S+)", line)
                dport_match = re.search(r"--dport\s+(\S+)", line)
                log_prefix = f"BF_{name}:" in line
                rules.append(FirewallRule(
                    name=name,
                    action=action_map.get(target, "deny"),
                    protocol=proto_match.group(1) if proto_match else "any",
                    src_cidr=src_match.group(1) if src_match else "any",
                    dst_cidr=dst_match.group(1) if dst_match else "any",
                    dst_port=dport_match.group(1) if dport_match else "any",
                    log=log_prefix,
                ))
        return rules

    def apply_firewall_rule(self, rule: FirewallRule, via: str = "nbi") -> None:
        """Apply firewall rule via iptables.

        L7 fields (application, application_category) are not supported
        on LinuxSDWANRouter (no DPI engine).  If set, a warning is logged
        and the rule is applied using only L3/L4 match criteria.
        """
        if rule.application or rule.application_category:
            _LOGGER.warning(
                "%s: L7 fields (application=%r, application_category=%r) "
                "ignored — LinuxSDWANRouter has no DPI engine. "
                "Rule %r applied with L3/L4 match only.",
                self.device_name, rule.application,
                rule.application_category, rule.name,
            )
        chain = "INPUT" if rule.dst_cidr != "any" else "FORWARD"
        action_map = {"allow": "ACCEPT", "deny": "DROP", "alert": "LOG"}
        target = action_map.get(rule.action, "DROP")
        cmd_parts = [f"iptables -A {chain}"]
        if rule.protocol != "any":
            cmd_parts.append(f"-p {rule.protocol}")
        if rule.src_cidr != "any":
            cmd_parts.append(f"-s {rule.src_cidr}")
        if rule.dst_cidr != "any":
            cmd_parts.append(f"-d {rule.dst_cidr}")
        if rule.dst_port != "any" and rule.protocol in ("tcp", "udp"):
            cmd_parts.append(f"--dport {rule.dst_port}")
        if rule.log:
            log_cmd = " ".join(cmd_parts) + f' -j LOG --log-prefix "BF_{rule.name}: "'
            self._console.execute_command(log_cmd)
        cmd_parts.append(f"-j {target}")
        cmd_parts.append(f'-m comment --comment "bf_{rule.name}"')
        self._console.execute_command(" ".join(cmd_parts))

    def remove_firewall_rule(self, name: str, via: str = "nbi") -> None:
        """Remove iptables rules matching the boardfarm comment tag."""
        for chain in ("INPUT", "FORWARD", "OUTPUT"):
            self._console.execute_command(
                f'iptables -S {chain} | grep "bf_{name}" | '
                f"sed 's/-A/-D/' | while read rule; do iptables $rule; done"
            )

    # ── SLA monitoring ──────────────────────────────────────────

    def configure_sla_policy(self, policy: SLAPolicy) -> None:
        """Define an SLA policy with quality thresholds.

        On LinuxSDWANRouter the declarative model is emulated: defining
        the policy stores it; the probe daemon is (re)started automatically
        during boot via ``_start_sla_from_env``.
        """
        self._sla_policies[policy.name] = policy
        _LOGGER.info(
            "%s: SLA policy %r configured "
            "(lat=%g jit=%g loss=%g%%)",
            self.device_name,
            policy.name,
            policy.max_latency_ms,
            policy.max_jitter_ms,
            policy.max_loss_percent,
        )

    def remove_sla_policy(self, name: str) -> None:
        """Remove an SLA policy and unbind it from all WAN links."""
        self._sla_policies.pop(name, None)
        labels_to_unbind = [
            label for label, pname in self._sla_bindings.items() if pname == name
        ]
        for label in labels_to_unbind:
            del self._sla_bindings[label]
        if self._sla_monitoring_active and not self._sla_bindings:
            self._stop_sla_monitoring()
        _LOGGER.info(
            "%s: SLA policy %r removed (unbound from %s)",
            self.device_name, name, labels_to_unbind,
        )

    def _apply_sla_binding(
        self, wan_label: str, policy_name: str
    ) -> None:
        """Bind an SLA policy to a WAN link (internal)."""
        if policy_name not in self._sla_policies:
            raise ValueError(
                f"SLA policy {policy_name!r} not configured. "
                f"Available: {list(self._sla_policies)}"
            )
        if wan_label not in self._wan_interfaces:
            raise KeyError(
                f"Unknown WAN label {wan_label!r}"
            )
        self._sla_bindings[wan_label] = policy_name
        _LOGGER.info(
            "%s: SLA policy %r bound to %s",
            self.device_name, policy_name, wan_label,
        )

    def _build_sla_config(self) -> dict:
        """Build the JSON config dict for the SLA probe daemon."""
        interval = getattr(self, "_probe_interval_ms", 100)
        failover = getattr(self, "_failover_threshold", 3)
        recovery = getattr(self, "_recovery_threshold", 5)
        links: dict = {}
        for label, policy_name in self._sla_bindings.items():
            policy = self._sla_policies[policy_name]
            gateway = self._wan_gateways.get(label)
            if not gateway:
                continue
            links[label] = {
                "gateway": gateway,
                "interface": self._wan_interfaces[label],
                "metric": self._wan_metrics.get(label, 0),
                "sla": {
                    "max_latency_ms": policy.max_latency_ms,
                    "max_jitter_ms": policy.max_jitter_ms,
                    "max_loss_percent": policy.max_loss_percent,
                },
            }
        return {
            "probe_interval_ms": interval,
            "window_size": 10,
            "failover_threshold": failover,
            "recovery_threshold": recovery,
            "links": links,
        }

    def _start_sla_monitoring(self) -> None:
        """Push config and start the SLA probe daemon on the device."""
        if not self._sla_bindings:
            _LOGGER.warning(
                "%s: No SLA bindings configured, skipping "
                "SLA monitoring start",
                self.device_name,
            )
            return
        config = self._build_sla_config()
        config_json = json.dumps(config, indent=2)
        config_path = "/etc/sdwan/sla_config.json"
        container = self._get_container_name()
        if container:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as f:
                f.write(config_json)
                f.flush()
                host_path = f.name
            try:
                subprocess.run(
                    [
                        "docker", "cp", host_path,
                        f"{container}:{config_path}",
                    ],
                    check=True,
                )
            finally:
                Path(host_path).unlink(missing_ok=True)
        else:
            self._console.execute_command(
                f"cat > {config_path} << 'SLAEOF'\n"
                f"{config_json}\nSLAEOF"
            )
        self._console.execute_command(
            "pkill -f sla_probe.py 2>/dev/null || true"
        )
        self._console.execute_command(
            f"nohup python3 /opt/sdwan/sla_probe.py {config_path} "
            "> /var/log/sla_probe.log 2>&1 &"
        )
        sleep(0.3)
        pid_out = self._console.execute_command(
            "pgrep -f sla_probe.py || true"
        )
        has_pid = any(
            line.strip().isdigit()
            for line in pid_out.strip().splitlines()
        )
        if not has_pid:
            log_out = self._console.execute_command(
                "tail -5 /var/log/sla_probe.log 2>/dev/null"
                " || true"
            )
            raise DeviceBootFailure(
                f"SLA probe daemon failed to start on "
                f"{self.device_name}. Log:\n{log_out}"
            )
        self._sla_monitoring_active = True
        _LOGGER.info(
            "SLA probe daemon started on %s "
            "(links: %s)",
            self.device_name,
            list(self._sla_bindings),
        )

    def _stop_sla_monitoring(self) -> None:
        """Stop the SLA probe daemon."""
        self._console.execute_command(
            "pkill -TERM -f sla_probe.py 2>/dev/null || true"
        )
        sleep(0.5)
        self._sla_monitoring_active = False
        _LOGGER.info(
            "SLA probe daemon stopped on %s",
            self.device_name,
        )

    def get_link_health(
        self, wan_label: str
    ) -> LinkHealthReport:
        """Query current health metrics from the SLA probe daemon."""
        output = self._console.execute_command(
            "cat /tmp/sla_status.json 2>/dev/null || "
            "echo '{}'"
        )
        try:
            status = json.loads(self._extract_json(output))
        except json.JSONDecodeError:
            return LinkHealthReport(
                state="unknown",
                route_installed=True,
                avg_rtt_ms=None,
                jitter_ms=None,
                loss_percent=100.0,
                sla_compliant=False,
            )
        link_data = status.get(wan_label, {})
        if not link_data:
            raise KeyError(
                f"WAN label {wan_label!r} not found in SLA "
                f"status. Available: {list(status)}"
            )
        state = link_data.get("state", "unknown")
        return LinkHealthReport(
            state=state,
            route_installed=link_data.get(
                "route_installed", True
            ),
            avg_rtt_ms=link_data.get("avg_rtt_ms"),
            jitter_ms=link_data.get("jitter_ms"),
            loss_percent=link_data.get("loss_percent", 100.0),
            sla_compliant=(state == "up"),
        )

    def _configure_default_sla(
        self, env_config: dict | None = None
    ) -> None:
        """Configure SLA monitoring from environment config defaults.

        Called during boot to apply sla_defaults from bf_env_sdwan.json
        to all WAN links.  Implementation-specific fields (probe_interval_ms,
        failover_threshold, recovery_threshold) are read from the env config
        but stored separately since SLAPolicy only carries the universal
        thresholds.
        """
        defaults = {}
        if env_config:
            defaults = env_config.get("sla_defaults", {})
        if not defaults:
            defaults = {
                "max_latency_ms": 150,
                "max_jitter_ms": 30,
                "max_loss_percent": 10,
            }
        self._probe_interval_ms = defaults.get("probe_interval_ms", 100)
        self._failover_threshold = defaults.get("failover_threshold", 3)
        self._recovery_threshold = defaults.get("recovery_threshold", 5)
        policy = SLAPolicy(
            name="default",
            max_latency_ms=defaults.get("max_latency_ms", 150),
            max_jitter_ms=defaults.get("max_jitter_ms", 30),
            max_loss_percent=defaults.get("max_loss_percent", 10),
        )
        self.configure_sla_policy(policy)
        for label in self._wan_interfaces:
            if label in self._wan_gateways:
                self._apply_sla_binding(label, "default")

    @hookimpl
    def boardfarm_skip_boot(self) -> None:
        """Boardfarm hook - initialize device without full boot."""
        _LOGGER.info("Initializing %s (%s)", self.device_name, self.device_type)
        self._connect()

    @hookimpl
    async def boardfarm_skip_boot_async(self) -> None:
        """Boardfarm hook - initialize device (async)."""
        _LOGGER.info("Initializing %s (%s)", self.device_name, self.device_type)
        await self._connect_async()

    @hookimpl
    def boardfarm_device_boot(self, device_manager: "DeviceManager") -> None:
        """Boardfarm hook - boot the WAN edge device.

        Connect, power cycle (for local_cmd/docker_exec), wait for
        interfaces, install FRR routes, then configure and start SLA
        monitoring from environment config defaults.
        """
        _LOGGER.info("Booting %s (%s)", self.device_name, self.device_type)
        self._connect()
        conn_type = self._config.get("connection_type", "authenticated_ssh")
        if conn_type in ("local_cmd", "docker_exec"):
            _LOGGER.info(
                "Power cycling %s (connection_type=%s)",
                self.device_name, conn_type,
            )
            self.power_cycle()
            self._wait_for_interfaces()
            self._wait_for_frr()
            self._start_sla_from_env(device_manager)
        else:
            _LOGGER.info(
                "Skipping power_cycle for %s (connection_type=%s)",
                self.device_name, conn_type,
            )

    @hookimpl
    async def boardfarm_device_boot_async(
        self, device_manager: "DeviceManager"
    ) -> None:
        """Boardfarm hook - boot the WAN edge device (async)."""
        _LOGGER.info("Booting %s (%s)", self.device_name, self.device_type)
        await self._connect_async()
        conn_type = self._config.get("connection_type", "authenticated_ssh")
        if conn_type in ("local_cmd", "docker_exec"):
            _LOGGER.info(
                "Power cycling %s (connection_type=%s)",
                self.device_name, conn_type,
            )
            self.power_cycle()
            self._wait_for_interfaces()
            self._wait_for_frr()
            self._start_sla_from_env(device_manager)
        else:
            _LOGGER.info(
                "Skipping power_cycle for %s (connection_type=%s)",
                self.device_name, conn_type,
            )

    def _start_sla_from_env(
        self, device_manager: "DeviceManager"
    ) -> None:
        """Read SLA defaults from merged config and start monitoring.

        The ``sla_defaults`` dict comes from ``bf_env_sdwan.json``
        ``environment_def.sdwan`` and is merged into ``self._config``
        by :func:`boardfarm3.lib.boardfarm_config.get_boardfarm_config`.
        """
        self._configure_default_sla(self._config)
        self._start_sla_monitoring()

    @hookimpl
    def boardfarm_shutdown_device(self) -> None:
        """Boardfarm hook - shutdown device."""
        _LOGGER.info("Shutdown %s (%s)", self.device_name, self.device_type)
        if self._sla_monitoring_active:
            try:
                self._stop_sla_monitoring()
            except Exception:
                pass
        self._disconnect()
