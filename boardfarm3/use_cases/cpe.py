"""Use Cases to check the performance of CPE."""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from string import Template
from typing import TYPE_CHECKING, Any, Literal

from boardfarm3.exceptions import UseCaseFailure

if TYPE_CHECKING:
    from collections.abc import Generator

    from boardfarm3.templates.acs import ACS
    from boardfarm3.templates.cpe import CPE
    from boardfarm3.templates.lan import LAN
    from boardfarm3.templates.wan import WAN
    from boardfarm3.templates.wlan import WLAN


_TOO_MANY_NTPS = 1

_UPNP_URL = Template("http://$IP:49152/IGDdevicedesc_brlan0.xml")


def get_cpu_usage(board: CPE) -> float:
    """Return the current CPU usage of CPE.

    .. hint:: This Use Case implements statements from the test suite such as:

        - Return the current CPU usage of CPE.

    :param board: CPE device instance
    :type board: CPE
    :return: current CPU usage of the CPE
    :rtype: float
    """
    return board.sw.get_load_avg()


def get_memory_usage(board: CPE) -> dict[str, int]:
    """Return the memory usage of CPE.

    .. hint:: This Use Case implements statements from the test suite such as:

        - Return the memory usage of CPE.

    :param board: CPE device instance
    :type board: CPE
    :return: current memory utilization of the CPE
    :rtype: dict[str, int]
    """
    return board.sw.get_memory_utilization()


def create_upnp_rule(  # noqa: PLR0913
    device: LAN | WLAN,
    int_port: str,
    ext_port: str,
    protocol: str,
    extra_args: str,
    url: str | None = None,
) -> str:
    """Create UPnP rule on the device.

    .. hint:: This Use Case implements statements from the test suite such as:

        - Create UPnP rule through cli.

    :param device: LAN or WLAN device instance
    :type device: LAN or WLAN
    :param int_port: internal port for UPnP
    :type int_port: str
    :param ext_port: external port for UPnP
    :type ext_port: str
    :param protocol: protocol to be used
    :type protocol: str
    :param extra_args: additional arguments to be passed to the upnp command
    :type extra_args: str
    :param url: url to be used
    :type url: str | None
    :return: output of UPnP add port command
    :rtype: str
    """
    ip_addr = device.get_interface_ipv4addr(device.iface_dut)
    if url is None:
        url = _UPNP_URL.safe_substitute(IP=device.get_default_gateway())
    return device.create_upnp_rule(
        device.iface_dut, ip_addr, int_port, ext_port, protocol, extra_args, url
    )


def delete_upnp_rule(
    device: LAN | WLAN, ext_port: str, protocol: str, url: str | None
) -> str:
    """Delete UPnP rule on the device.

    .. hint:: This Use Case implements statements from the test suite such as:

        - Delete UPnP rule through cli.

    :param device: LAN or WLAN device instance
    :type device: LAN or WLAN
    :param ext_port: external port for UPnP
    :type ext_port: str
    :param protocol: protocol to be used
    :type protocol: str
    :param url: url to be used
    :type url: str | None
    :return: output of UPnP delete port command
    :rtype: str
    """
    if url is None:
        url = _UPNP_URL.safe_substitute(IP=device.get_default_gateway())
    return device.delete_upnp_rule(device.iface_dut, ext_port, protocol, url)


def is_ntp_synchronized(board: CPE) -> bool:
    """Get the NTP synchronization status.

    Sample block of the output

    .. code-block:: python

        [
            {
                "remote": "2001:dead:beef:",
                "refid": ".XFAC.",
                "st": 16,
                "t": "u",
                "when": 65,
                "poll": 18,
                "reach": 0,
                "delay": 0.0,
                "offset": 0.0,
                "jitter": 0.0,
                "state": "*",
            }
        ]

    This Use Case validates the 'state' from the parsed output and returns bool based on
    the value present in it. The meaning of the indicators are given below,

    '*' - synchronized candidate
    '#' - selected but not synchronized
    '+' - candidate to be selected
    [x/-/ /./None] - discarded candidate

    :param board: CPE device instance
    :type board: CPE
    :raises ValueError: when the output has more than one list item
    :return: True if NTP is synchronized, false otherwise
    :rtype: bool
    """
    ntp_output = board.sw.get_ntp_sync_status()
    if len(ntp_output) == 0:
        msg = "No NTP server available to the device"
        raise ValueError(msg)
    if len(ntp_output) > _TOO_MANY_NTPS:
        msg = "Unclear NTP status. There is more than one NTP server present"
        raise ValueError(msg)
    return ntp_output[0]["state"] == "*"


def enable_logs(board: CPE, component: str) -> None:
    """Enable logs for the specified component on the CPE.

    .. note::
        - The component can be one of "voice" and "pacm" for mv2p
        - The component can be one of "voice", "docsis", "common_components",
            "gw", "vfe", "vendor_cbn", "pacm" for mv1

    :param board: The board instance
    :type board: CPE
    :param component: The component for which logs have to be enabled.
    :type component: str
    """
    board.sw.enable_logs(component=component, flag="enable")


def disable_logs(board: CPE, component: str) -> None:
    """Disable logs for the specified component on the CPE.

    .. note::
        - The component can be one of "voice" and "pacm" for mv2p
        - The component can be one of "voice", "docsis", "common_components",
            "gw", "vfe", "vendor_cbn", "pacm" for mv1

    :param board: The board instance
    :type board: CPE
    :param component: The component for which logs have to disabled.
    :type component: str
    """
    board.sw.enable_logs(component=component, flag="disable")


def factory_reset(board: CPE, method: None | str = None) -> bool:
    """Perform factory reset CPE via given method.

    :param board: The board instance.
    :type board: CPE
    :param method: Factory reset method
    :type method: None | str
    :return: True on successful factory reset
    :rtype: bool
    """
    return board.sw.factory_reset(method)


def get_seconds_uptime(board: CPE) -> float:
    """Return board uptime in seconds.

    :param board: The board instance
    :type board: CPE
    :return: board uptime in seconds
    :rtype: float
    """
    return board.sw.get_seconds_uptime()


def is_tr069_agent_running(board: CPE) -> bool:
    """Check if TR069 agent is running or not.

    :param board: The board instance
    :type board: CPE
    :return: True if agent is running, false otherwise
    :rtype: bool
    """
    return board.sw.is_tr069_connected()


def get_cpe_provisioning_mode(board: CPE) -> str:
    """Get the provisioning mode of the board.

    :param board: The board object, from which the provisioning mode is fetched.
    :type board: CPE
    :return: The provisioning mode of the board.
    :rtype: str
    """
    return board.sw.get_provision_mode()


def board_reset_via_console(board: CPE) -> None:
    """Reset board via console.

    .. hint:: This Use Case implements statements from the test suite such as:

        - Reboot from console.

    :param board: The board instance
    :type board: CPE
    """
    board.sw.reset(method="sw")
    board.sw.wait_for_boot()


@contextmanager
def tcpdump(
    fname: str,
    interface: str,
    board: CPE,
    filters: dict | None = None,
) -> Generator[str]:
    """Contextmanager to perform tcpdump on the board.

    Start ``tcpdump`` on the board console and kill it outside its scope

    :param fname: the filename or the complete path of the resource
    :type fname: str
    :param interface: interface name on which the tcp traffic will listen to
    :type interface: str
    :param board: CPE device instance
    :type board: CPE
    :param filters: filters as key value pair(eg: {"-v": "", "-c": "4"})
    :type filters: dict | None
    :yield: yields the process id of the tcp capture started
    :rtype: Generator[str, None, None]
    """
    pid: str = ""
    try:
        pid = board.sw.nw_utility.start_tcpdump(fname, interface, filters=filters)
        yield pid
    finally:
        board.sw.nw_utility.stop_tcpdump(pid)


def read_tcpdump(
    fname: str,
    board: CPE,
    protocol: str = "",
    opts: str = "",
    rm_pcap: bool = True,
) -> str:
    """Read the tcpdump packets and delete the capture file afterwards.

    :param fname: filename or the complete path of the pcap file
    :type fname: str
    :param board: CPE device instance
    :type board: CPE
    :param protocol: protocol to filter, defaults to ""
    :type protocol: str
    :param opts: defaults to ""
    :type opts: str
    :param rm_pcap: defaults to True
    :type rm_pcap: bool
    :return: output of tcpdump read command
    :rtype: str
    """
    return board.sw.nw_utility.read_tcpdump(
        fname,
        protocol=protocol,
        opts=opts,
        rm_pcap=rm_pcap,
    )


def transfer_file_via_scp(  # pylint: disable=protected-access  # noqa: PLR0913
    source_dev: CPE,
    source_file: str,
    dest_file: str,
    dest_host: LAN | WAN,
    action: Literal["download", "upload"],
    port: int | str = 22,
    ipv6: bool = False,
) -> None:
    """Copy files and directories between the board and the remote host.

    Copy is made over SSH.

    :param source_dev: CPE device instance
    :type source_dev: CPE
    :param source_file: path on the board
    :type source_file: str
    :param dest_file: path on the remote host
    :type dest_file: str
    :param dest_host: the remote host instance
    :type dest_host: LAN | WAN
    :param port: host port
    :type port: int | str
    :param action: scp action to perform i.e upload, download
    :type action: Literal["download", "upload"]
    :param port: host port, defaults to 22
    :type port: str
    :param ipv6: whether scp should be done to IPv4 or IPv6, defaults to IPv4
    :type ipv6: bool
    """
    (src, dst) = (
        (source_file, dest_file) if action == "upload" else (dest_file, source_file)
    )
    # TODO: private members should not be used, BOARDFARM-5040
    username = dest_host._username  # type: ignore[union-attr]  # noqa: SLF001
    password = dest_host._password  # type: ignore[union-attr]  # noqa: SLF001
    ip_addr = (
        dest_host.get_interface_ipv6addr(dest_host.iface_dut)
        if ipv6
        else dest_host.get_interface_ipv4addr(dest_host.iface_dut)
    )
    source_dev.sw.nw_utility.scp(ip_addr, port, username, password, src, dst, action)


def upload_file_to_tftp(  # pylint: disable=too-many-arguments  # noqa: PLR0913
    source_dev: CPE,
    source_file: str,
    tftp_server: LAN | WAN,
    path_on_tftpserver: str,
    ipv6: bool = False,
    timeout: int = 60,
) -> None:
    """Transfer file onto tftp server.

    .. hint:: This Use Case helps to copy files from board to tftp servre

        - can be used after a tcpdump on board

    :param source_dev: CPE device instance
    :type source_dev: CPE
    :param source_file: Path on the board
    :type source_file: str
    :param tftp_server: the remote tftp server instance
    :type tftp_server: LAN | WAN
    :param path_on_tftpserver: Path on the tftp server
    :type path_on_tftpserver: str
    :param ipv6: if scp should be done to ipv4 or ipv6, defaults to ipv4
    :type ipv6: bool
    :param timeout: timeout value for the usecase
    :type timeout: int
    :raises UseCaseFailure: when file not found
    """
    serv_tftp_folder = "/tftpboot"
    server_ip_addr = (
        tftp_server.get_interface_ipv6addr(tftp_server.iface_dut)
        if ipv6
        else tftp_server.get_interface_ipv4addr(tftp_server.iface_dut)
    )
    _, filename = os.path.split(source_file)
    file_location_on_server = f"{serv_tftp_folder}/{filename}"
    tftp_server.console.execute_command(
        f"chmod 777 {serv_tftp_folder}", timeout=timeout
    )
    source_dev.sw.nw_utility.tftp(
        server_ip_addr, source_file, filename, timeout=timeout
    )
    # move file to given tftp location and perform check of transfer
    mv_command = f"mv {file_location_on_server} {path_on_tftpserver}"
    output = tftp_server.console.execute_command(mv_command, timeout=timeout)
    if "No such file or directory" in output:
        msg = f"file not found {output}"
        raise UseCaseFailure(msg)


# =============================================================================
# Reboot and TR-069 Client Management
# =============================================================================


def wait_for_reboot_completion(
    board: CPE,
    timeout: int = 60,
    poll_interval: int = 1,
) -> bool:
    """Wait for CPE to complete reboot process.

    This function monitors the CPE for reboot completion by:
    1. Waiting for the CPE to become unresponsive (reboot started)
    2. Waiting for the CPE to become responsive again (reboot completed)

    .. hint:: This Use Case implements statements from the test suite such as:

        - The CPE executes the reboot command and restarts
        - Wait for CPE to become unresponsive then responsive

    :param board: CPE device instance
    :type board: CPE
    :param timeout: Maximum wait time in seconds
    :type timeout: int
    :param poll_interval: Interval between checks in seconds
    :type poll_interval: int
    :return: True if reboot completed successfully
    :rtype: bool
    :raises UseCaseFailure: If reboot does not complete within timeout
    """
    _LOGGER.info("Waiting for CPE reboot completion (timeout=%ds)...", timeout)

    # Phase 1: Wait for CPE to become unresponsive
    _LOGGER.info("Phase 1: Waiting for CPE to become unresponsive...")
    unresponsive_timeout = timeout // 2
    became_unresponsive = False

    for _ in range(unresponsive_timeout // poll_interval):
        try:
            console = board.hw.get_console("console")
            console.execute_command("echo test", timeout=2)
            time.sleep(poll_interval)
        except Exception:  # noqa: BLE001
            became_unresponsive = True
            _LOGGER.info("CPE became unresponsive - reboot started")
            break

    if not became_unresponsive:
        msg = "CPE did not become unresponsive - reboot may not have started"
        raise UseCaseFailure(msg)

    # Phase 2: Wait for CPE to become responsive again
    _LOGGER.info("Phase 2: Waiting for CPE to become responsive...")
    responsive_timeout = timeout // 2
    became_responsive = False

    for _ in range(responsive_timeout // poll_interval):
        try:
            console = board.hw.get_console("console")
            console.execute_command("echo test", timeout=5)
            became_responsive = True
            _LOGGER.info("CPE is responsive - reboot completed")
            break
        except Exception:  # noqa: BLE001
            time.sleep(poll_interval)

    if not became_responsive:
        msg = "CPE did not become responsive after reboot"
        raise UseCaseFailure(msg)

    return True


def stop_tr069_client(board: CPE) -> None:
    """Stop TR-069 client on CPE (make unreachable for TR-069).

    Stops the TR-069 client process (cwmp_plugin) on the CPE, which
    prevents the CPE from receiving connection requests from the ACS
    and participating in TR-069 sessions.

    .. hint:: This Use Case implements statements from the test suite such as:

        - The CPE is unreachable for TR-069 sessions
        - Stop the TR-069 agent

    :param board: CPE device instance
    :type board: CPE
    :raises UseCaseFailure: If TR-069 client cannot be stopped
    """
    _LOGGER.info("Stopping TR-069 client on CPE...")

    console = board.hw.get_console("console")

    # Stop using init script
    console.execute_command("/etc/init.d/cwmp_plugin stop", timeout=10)

    # Wait for process to stop
    time.sleep(2)

    # Verify TR-069 client is stopped
    result = console.execute_command("pgrep cwmp_plugin", timeout=5)
    if result.strip():
        msg = "TR-069 client still running - could not stop cwmp_plugin"
        raise UseCaseFailure(msg)

    _LOGGER.info("TR-069 client stopped successfully")


def start_tr069_client(board: CPE) -> None:
    """Start TR-069 client on CPE (make reachable for TR-069).

    Starts the TR-069 client process (cwmp_plugin) on the CPE, which
    allows the CPE to receive connection requests from the ACS and
    participate in TR-069 sessions. The client will send an Inform
    message to the ACS when it starts.

    .. hint:: This Use Case implements statements from the test suite such as:

        - When the CPE comes online, it connects to the ACS
        - Start the TR-069 agent

    :param board: CPE device instance
    :type board: CPE
    :raises UseCaseFailure: If TR-069 client cannot be started
    """
    _LOGGER.info("Starting TR-069 client on CPE...")

    console = board.hw.get_console("console")

    # Start using init script
    console.execute_command("/etc/init.d/cwmp_plugin start", timeout=10)

    # Wait for process to start
    time.sleep(5)

    # Verify TR-069 client is running
    result = console.execute_command("pgrep cwmp_plugin", timeout=5)
    if not result.strip():
        msg = "TR-069 client failed to start - cwmp_plugin not running"
        raise UseCaseFailure(msg)

    _LOGGER.info("TR-069 client started successfully")


def refresh_console_connection(
    board: CPE,
    device_name: str | None = None,
) -> bool:
    """Refresh CPE console connection after reboot.

    Disconnects and reconnects to the CPE console. This is necessary
    after a reboot to ensure the console connection is valid.

    .. hint:: This Use Case implements statements from the test suite such as:

        - Reconnect to CPE console after reboot
        - Refresh console connection

    :param board: CPE device instance
    :type board: CPE
    :param device_name: Name of the device for reconnection (optional)
    :type device_name: str | None
    :return: True if reconnection successful
    :rtype: bool
    """
    _LOGGER.info("Refreshing CPE console connection...")

    # Disconnect from consoles
    try:
        board.hw.disconnect_from_consoles()
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("Error disconnecting from consoles (may be expected): %s", e)

    # Reconnect to consoles
    try:
        name = device_name or getattr(board, "device_name", "cpe")
        board.hw.connect_to_consoles(name)
        _LOGGER.info("Console connection refreshed successfully")
        return True
    except Exception as e:  # noqa: BLE001
        _LOGGER.error("Failed to refresh console connection: %s", e)
        return False


def get_console_uptime_seconds(board: CPE) -> int:
    """Return CPE uptime in seconds using console for reliability.

    Uses direct console access to get uptime, which is more reliable
    during boot sequences when the software layer may not be fully
    operational.

    .. hint:: This Use Case implements statements from the test suite such as:

        - Get CPE uptime via console
        - Check uptime to verify reboot

    :param board: CPE device instance
    :type board: CPE
    :return: Uptime in seconds
    :rtype: int
    """
    try:
        return int(board.sw.get_seconds_uptime())
    except Exception:  # noqa: BLE001
        # Fallback to direct console command
        console = board.hw.get_console("console")
        output = console.execute_command("cut -d' ' -f1 /proc/uptime")
        return int(float(output.strip() or "0"))


def verify_config_preservation(
    board: CPE,
    acs: ACS,
    config_before: dict[str, Any],
) -> list[str]:
    """Verify CPE configuration preserved after reboot.

    Compares key configuration parameters captured before reboot with
    current values to verify they were preserved.

    .. hint:: This Use Case implements statements from the test suite such as:

        - The CPE's configuration and operational state are preserved after reboot
        - Verify config parameters match pre-reboot values

    :param board: CPE device instance
    :type board: CPE
    :param acs: ACS device instance
    :type acs: ACS
    :param config_before: Configuration captured before reboot
    :type config_before: dict[str, Any]
    :return: List of verification errors (empty if all preserved)
    :rtype: list[str]
    """
    # Import here to avoid circular imports
    from boardfarm3.use_cases import acs as acs_use_cases

    _LOGGER.info("Verifying configuration preservation...")

    if not config_before:
        _LOGGER.warning("No configuration captured before reboot")
        return ["No configuration captured before reboot"]

    verification_errors: list[str] = []
    cpe_id = board.sw.cpe_id

    for config_key, config_data in config_before.items():
        if not isinstance(config_data, dict):
            continue

        # Simple value verification
        if "gpv_param" in config_data and "value" in config_data:
            try:
                current_value = acs_use_cases.get_parameter_value(
                    acs, board, config_data["gpv_param"]
                )
                expected_value = str(config_data["value"])
                if current_value != expected_value:
                    verification_errors.append(
                        f"{config_key} changed: {expected_value} → {current_value}"
                    )
                else:
                    _LOGGER.info("%s preserved: %s", config_key, current_value)
            except Exception as e:  # noqa: BLE001
                verification_errors.append(f"Could not verify {config_key}: {e}")

        # Dict-based verification (for complex configs like users, wifi_ssids)
        elif "count" in config_data and "items" in config_data:
            try:
                # Verify count
                if config_data.get("count"):
                    count_gpv = config_data["count"]["gpv_param"]
                    expected_count = config_data["count"]["value"]
                    result = acs.nbi.GPV(count_gpv, cpe_id=cpe_id, timeout=30)
                    if result:
                        current_count = int(result[0].get("value", 0))
                        if current_count != expected_count:
                            verification_errors.append(
                                f"{config_key} count changed: "
                                f"{expected_count} → {current_count}"
                            )

                # Verify items
                for item_idx, item_fields in config_data.get("items", {}).items():
                    for field_name, field_data in item_fields.items():
                        if not isinstance(field_data, dict):
                            continue
                        if "gpv_param" not in field_data or "value" not in field_data:
                            continue

                        try:
                            current_value = acs_use_cases.get_parameter_value(
                                acs, board, field_data["gpv_param"]
                            )
                            expected_value = field_data["value"]

                            # Handle boolean comparison
                            if isinstance(expected_value, bool):
                                current_bool = current_value.lower() in (
                                    "true",
                                    "1",
                                    "enabled",
                                )
                                if current_bool != expected_value:
                                    verification_errors.append(
                                        f"{config_key} {item_idx} {field_name} "
                                        f"changed: {expected_value} → {current_bool}"
                                    )
                            elif str(current_value) != str(expected_value):
                                verification_errors.append(
                                    f"{config_key} {item_idx} {field_name} "
                                    f"changed: {expected_value} → {current_value}"
                                )
                            else:
                                _LOGGER.info(
                                    "%s %s %s preserved",
                                    config_key,
                                    item_idx,
                                    field_name,
                                )
                        except Exception as e:  # noqa: BLE001
                            verification_errors.append(
                                f"Could not verify {config_key} {item_idx} "
                                f"{field_name}: {e}"
                            )

            except Exception as e:  # noqa: BLE001
                verification_errors.append(f"Could not verify {config_key}: {e}")

    if verification_errors:
        _LOGGER.warning("Configuration verification errors: %s", verification_errors)
    else:
        _LOGGER.info("All configuration parameters preserved after reboot")

    return verification_errors
