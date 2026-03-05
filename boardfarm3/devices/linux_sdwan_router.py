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
    LinkStatus,
    PathMetrics,
    RouteEntry,
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
        # When bring_wan_up() is called, the route is re-installed with this metric
        # because the kernel automatically removes it when the interface went down.
        # Must match the metrics used by the init script's ip route commands.
        self._wan_metrics: dict[str, int] = config.get("wan_metrics", {})

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
    def console(self) -> BoardfarmPexpect:
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
        output = self._console.execute_command(cmd)
        if "Network is unreachable" in output:
            raise ValueError(
                f"No route to {dst} (Network is unreachable). "
                "FRR may not have installed routes yet; ensure boot completed."
            )
        match = re.search(r"dev\s+(\S+)", output)
        if not match:
            raise ValueError(f"Could not parse output from 'ip route get {dst}': {output}")
        physical = match.group(1)
        return self._to_logical(physical)

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
        """Apply PBR policy via FRR pbr-map."""
        name = policy.get("name", "pbr-policy")
        match_cfg = policy.get("match", {})
        action_cfg = policy.get("action", {})
        prefer_wan = action_cfg.get("prefer_wan")
        if not prefer_wan:
            raise ValueError("policy.action.prefer_wan is required")
        gateway = self._wan_gateways.get(prefer_wan)
        if not gateway:
            raise ValueError(
                f"wan_gateways[{prefer_wan!r}] not configured; cannot apply policy"
            )
        dst_prefix = match_cfg.get("dst_prefix", "0.0.0.0/0")
        if dst_prefix == "any":
            dst_prefix = "0.0.0.0/0"
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

    def remove_policy(self, name: str, via: str = "nbi") -> None:
        """Remove PBR policy via FRR vtysh."""
        cmds = [
            "configure terminal",
            f"interface {self._lan_interface}",
            " no pbr-policy",
            " exit",
            f"no pbr-map {name}",
            "exit",
        ]
        self._run_vtysh(cmds)

    def bring_wan_down(self, label: str, via: str = "console") -> None:
        """Bring a WAN interface down."""
        physical = self._wan_interfaces.get(label)
        if not physical:
            raise KeyError(f"Unknown WAN label {label!r}")
        self._console.execute_command(f"ip link set {physical} down")

    def bring_wan_up(self, label: str, via: str = "console") -> None:
        """Bring a WAN interface up and restore its default route.

        The Linux kernel automatically removes a nexthop route when its
        interface goes down (see bring_wan_down).  After bringing the
        interface back up, the route must be re-installed explicitly.
        The kernel metric comes from wan_metrics config (must match the
        values used by the container init script).
        """
        physical = self._wan_interfaces.get(label)
        if not physical:
            raise KeyError(f"Unknown WAN label {label!r}")
        self._console.execute_command(f"ip link set {physical} up")
        gateway = self._wan_gateways.get(label)
        metric = self._wan_metrics.get(label)
        if gateway and metric is not None:
            self._console.execute_command(
                f"ip route replace default via {gateway} dev {physical} "
                f"metric {metric} proto static"
            )
            _LOGGER.debug(
                "%s bring_wan_up(%r): restored default route via %s metric %d",
                self.device_name, label, gateway, metric,
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

    def _wait_for_frr(self, timeout_s: int = 45) -> None:
        """Wait until kernel routes are ready AND vtysh responds.

        Three conditions are checked on every poll:

        1. **Connected routes** — ``ip route show`` lists at least one route
           per WAN interface (satisfied as soon as the interfaces are up).
        2. **Default route** — ``ip route show`` contains a ``default`` entry,
           confirming the init script has finished installing the kernel default
           routes (metric-differentiated WAN1/WAN2 routes).
        3. **FRR control plane** — ``vtysh -c "show version"`` completes
           without a "Cannot connect" error, so boardfarm can apply PBR
           policies via ``_run_vtysh()``.

        All three must be satisfied before this method returns.
        """
        wan_devs = set(self._wan_interfaces.values())
        elapsed = 0
        interval_s = 2
        routes_ok = False
        default_ok = False
        vtysh_ok = False
        while elapsed < timeout_s:
            if not routes_ok or not default_ok:
                route_out = self._console.execute_command("ip route show 2>/dev/null || true")
                routes_ok = all(f"dev {dev}" in route_out for dev in wan_devs)
                default_ok = "default" in route_out

            if not vtysh_ok:
                vtysh_out = self._console.execute_command(
                    "vtysh -c 'show version' 2>&1 || true"
                )
                vtysh_ok = (
                    "FRRouting" in vtysh_out
                    and "Cannot connect" not in vtysh_out
                    and "Failed to connect" not in vtysh_out
                )

            if routes_ok and default_ok and vtysh_ok:
                _LOGGER.info(
                    "FRR ready on %s (connected routes: %s, default route: OK, vtysh: OK)",
                    self.device_name,
                    sorted(wan_devs),
                )
                return

            _LOGGER.debug(
                "%s waiting for FRR: routes_ok=%s default_ok=%s vtysh_ok=%s (elapsed=%ds)",
                self.device_name, routes_ok, default_ok, vtysh_ok, elapsed,
            )
            sleep(interval_s)
            elapsed += interval_s

        missing = []
        if not routes_ok:
            missing.append("kernel routes on WAN interfaces")
        if not default_ok:
            missing.append("kernel default route (init script not complete?)")
        if not vtysh_ok:
            missing.append("vtysh connectivity")
        raise DeviceBootFailure(
            f"FRR not ready on {self.device_name} within {timeout_s}s: "
            f"{' and '.join(missing)} not available"
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

        Connect, power cycle (for local_cmd/docker_exec), then optionally wait
        for interfaces. No provisioning; device is ready for configuration.
        """
        _LOGGER.info("Booting %s (%s)", self.device_name, self.device_type)
        self._connect()
        conn_type = self._config.get("connection_type", "authenticated_ssh")
        if conn_type in ("local_cmd", "docker_exec"):
            _LOGGER.info("Power cycling %s (connection_type=%s)", self.device_name, conn_type)
            self.power_cycle()
            self._wait_for_interfaces()
            self._wait_for_frr()
        else:
            _LOGGER.info("Skipping power_cycle for %s (connection_type=%s)", self.device_name, conn_type)

    @hookimpl
    async def boardfarm_device_boot_async(self, device_manager: "DeviceManager") -> None:
        """Boardfarm hook - boot the WAN edge device (async)."""
        _LOGGER.info("Booting %s (%s)", self.device_name, self.device_type)
        await self._connect_async()
        conn_type = self._config.get("connection_type", "authenticated_ssh")
        if conn_type in ("local_cmd", "docker_exec"):
            _LOGGER.info("Power cycling %s (connection_type=%s)", self.device_name, conn_type)
            self.power_cycle()
            self._wait_for_interfaces()
            self._wait_for_frr()
        else:
            _LOGGER.info("Skipping power_cycle for %s (connection_type=%s)", self.device_name, conn_type)

    @hookimpl
    def boardfarm_shutdown_device(self) -> None:
        """Boardfarm hook - shutdown device."""
        _LOGGER.info("Shutdown %s (%s)", self.device_name, self.device_type)
        self._disconnect()
