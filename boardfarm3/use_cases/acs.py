"""ACS (Auto Configuration Server) use cases.

Provides high-level operations for ACS interactions including:
- Parameter get/set via TR-069
- Reboot task management
- Log monitoring and polling
- Connection request handling

Interface Selection:
    Many functions support a `via` parameter to select the interface:
    - "nbi" (default): Use NBI/REST API (faster, programmatic)
    - "gui": Use web GUI (tests GUI functionality)
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

from boardfarm3.exceptions import UseCaseFailure
from boardfarm3.lib.utils import retry

if TYPE_CHECKING:
    from boardfarm3.templates.acs import ACS
    from boardfarm3.templates.cpe import CPE

_LOGGER = logging.getLogger(__name__)

# Type alias for interface selection
InterfaceType = Literal["nbi", "gui"]

# Default log paths for GenieACS
_GENIEACS_CWMP_LOG = "/var/log/genieacs/genieacs-cwmp-access.log"
_GENIEACS_NBI_LOG = "/var/log/genieacs/genieacs-nbi-access.log"


def get_parameter_value(
    acs: ACS,
    cpe: CPE,
    parameter: str,
    timeout: int = 30,
    retries: int = 6,
    via: InterfaceType = "nbi",
) -> str:
    """Get TR-069 parameter value via ACS.

    .. hint:: This Use Case implements statements from the test suite such as:

        - Get the value of a TR-069 parameter via ACS
        - Verify CPE parameter value

    :param acs: ACS device instance
    :type acs: ACS
    :param cpe: CPE device instance
    :type cpe: CPE
    :param parameter: TR-069 parameter path
    :type parameter: str
    :param timeout: Operation timeout in seconds
    :type timeout: int
    :param retries: Number of retry attempts
    :type retries: int
    :param via: Interface to use ("nbi" for API, "gui" for web interface)
    :type via: InterfaceType
    :return: Parameter value as string
    :rtype: str
    :raises UseCaseFailure: If parameter cannot be retrieved
    """
    cpe_id = cpe.sw.cpe_id

    if via == "gui":
        return acs.gui.get_device_parameter_via_gui(cpe_id, parameter)

    # Default: NBI with retry logic
    def _fetch_gpv() -> str | None:
        result = acs.nbi.GPV(parameter, timeout=timeout, cpe_id=cpe_id)
        if not result:
            return None
        item = result[0]
        # Handle different response formats
        val = item.get("value") if isinstance(item, dict) else None
        if val is None:
            val = item.get("rval") if isinstance(item, dict) else None
        return str(val) if val is not None else None

    output = retry(_fetch_gpv, retries)
    if output is None:
        msg = f"GPV returned empty/malformed for {parameter}"
        raise UseCaseFailure(msg)
    return output


def set_parameter_value(
    acs: ACS,
    cpe: CPE,
    parameter: str,
    value: str,
    timeout: int = 30,
    via: InterfaceType = "nbi",
) -> bool:
    """Set TR-069 parameter value via ACS.

    .. hint:: This Use Case implements statements from the test suite such as:

        - Set the value of a TR-069 parameter via ACS
        - Configure CPE parameter

    :param acs: ACS device instance
    :type acs: ACS
    :param cpe: CPE device instance
    :type cpe: CPE
    :param parameter: TR-069 parameter path
    :type parameter: str
    :param value: Value to set
    :type value: str
    :param timeout: Operation timeout in seconds
    :type timeout: int
    :param via: Interface to use ("nbi" for API, "gui" for web interface)
    :type via: InterfaceType
    :return: True if successful
    :rtype: bool
    """
    cpe_id = cpe.sw.cpe_id

    if via == "gui":
        return acs.gui.set_device_parameter_via_gui(cpe_id, parameter, value)

    # Default: NBI
    result = acs.nbi.SPV({parameter: value}, timeout, cpe_id)
    return result in {0, 1}  # SPV returns 0 or 1 on success


def initiate_reboot(
    acs: ACS,
    cpe: CPE,
    command_key: str = "reboot",
    via: InterfaceType = "nbi",
) -> None:
    """Initiate CPE reboot via ACS.

    .. hint:: This Use Case implements statements from the test suite such as:

        - The operator initiates a reboot task on the ACS for the CPE
        - Reboot the CPE via TR-069

    :param acs: ACS device instance
    :type acs: ACS
    :param cpe: CPE device instance
    :type cpe: CPE
    :param command_key: Command key for the reboot task
    :type command_key: str
    :param via: Interface to use ("nbi" for API, "gui" for web interface)
    :type via: InterfaceType
    """
    cpe_id = cpe.sw.cpe_id

    if via == "gui":
        acs.gui.reboot_device_via_gui(cpe_id)
        return

    # Default: NBI
    acs.nbi.Reboot(CommandKey=command_key, cpe_id=cpe_id)


def _parse_log_timestamp(log_line: str) -> datetime | None:
    """Parse timestamp from a GenieACS log line.

    GenieACS logs use ISO 8601 format with UTC timezone:
    - "2024-01-01T12:00:00.123Z" (with milliseconds and Z timezone)
    - "2024-01-01T12:00:00Z" (without milliseconds)

    :param log_line: Log line to parse
    :type log_line: str
    :return: Parsed datetime object (naive, assumed UTC), or None if not found
    :rtype: datetime | None
    """
    # Try ISO format with Z timezone and optional milliseconds
    iso_z_match = re.search(
        r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?Z", log_line
    )
    if iso_z_match:
        timestamp_str = iso_z_match.group(1)
        milliseconds = iso_z_match.group(2)
        try:
            dt = datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%S")
            if milliseconds:
                microseconds = int(float(milliseconds) * 1000000)
                dt = dt.replace(microsecond=microseconds)
            return dt
        except ValueError:
            pass

    # Try proxy log format: "2025-11-19 16:41:17 [INFO] ..."
    proxy_match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", log_line)
    if proxy_match:
        timestamp_str = proxy_match.group(1)
        try:
            return datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

    # Try ISO format without Z (fallback)
    iso_match = re.search(
        r"(\d{4}[-/]\d{2}[-/]\d{2}[\sT]\d{2}:\d{2}:\d{2})", log_line
    )
    if iso_match:
        timestamp_str = iso_match.group(1).replace("T", " ").replace("/", "-")
        try:
            return datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

    return None


def _filter_logs_by_timestamp(
    log_lines: list[str], start_timestamp: datetime | None
) -> list[str]:
    """Filter log lines to only include entries after start_timestamp.

    :param log_lines: List of log lines to filter
    :type log_lines: list[str]
    :param start_timestamp: Timestamp to filter from (inclusive)
    :type start_timestamp: datetime | None
    :return: Filtered list of log lines
    :rtype: list[str]
    """
    if start_timestamp is None:
        return log_lines

    # Convert to naive UTC if timezone-aware
    if start_timestamp.tzinfo is not None:
        start_naive = start_timestamp.astimezone(timezone.utc)
        start_naive = start_naive.replace(tzinfo=None)
    else:
        start_naive = start_timestamp

    filtered = []
    for line in log_lines:
        if not line.strip():
            continue
        line_ts = _parse_log_timestamp(line)
        if line_ts is None or line_ts >= start_naive:
            filtered.append(line)
    return filtered


def _filter_logs_by_cpe_id(log_lines: list[str], cpe_id: str | None) -> list[str]:
    """Filter log lines to only include entries for a specific CPE.

    :param log_lines: List of log lines to filter
    :type log_lines: list[str]
    :param cpe_id: CPE ID to filter for, or None to return all
    :type cpe_id: str | None
    :return: Filtered list of log lines
    :rtype: list[str]
    """
    if cpe_id is None:
        return log_lines

    filtered = []
    for line in log_lines:
        if not line.strip():
            continue
        # Check multiple patterns for CPE ID
        if f" {cpe_id}:" in line or f" {cpe_id} " in line or cpe_id in line:
            filtered.append(line)
    return filtered


def wait_for_inform_message(
    acs: ACS,
    cpe_id: str,
    event_codes: list[str] | None = None,
    since: datetime | None = None,
    timeout: int = 120,
) -> bool:
    """Wait for Inform message from CPE in ACS logs.

    .. hint:: This Use Case implements statements from the test suite such as:

        - The CPE sends an Inform message to the ACS
        - Wait for post-reboot Inform with "1 BOOT,M Reboot" events

    :param acs: ACS device instance
    :type acs: ACS
    :param cpe_id: CPE identifier
    :type cpe_id: str
    :param event_codes: Expected event codes (e.g., ["1 BOOT", "M Reboot"])
    :type event_codes: list[str] | None
    :param since: Only consider logs after this timestamp
    :type since: datetime | None
    :param timeout: Maximum wait time in seconds
    :type timeout: int
    :return: True if Inform found
    :rtype: bool
    :raises UseCaseFailure: If Inform not found within timeout
    """
    _LOGGER.info("Waiting for Inform message from CPE %s...", cpe_id)

    poll_interval = 1
    max_attempts = timeout // poll_interval

    for attempt in range(max_attempts):
        try:
            acs_console = acs.console
            logs = acs_console.execute_command(
                f"tail -n 300 {_GENIEACS_CWMP_LOG} | grep -i inform",
                timeout=10,
            )

            log_lines = [line for line in logs.split("\n") if line.strip()]
            log_lines = _filter_logs_by_timestamp(log_lines, since)
            log_lines = _filter_logs_by_cpe_id(log_lines, cpe_id)

            # Check for Inform message
            for line in log_lines:
                if "inform" in line.lower():
                    # If event_codes specified, verify they're present
                    if event_codes:
                        if all(code in line for code in event_codes):
                            _LOGGER.info(
                                "Found Inform with event codes %s from CPE %s",
                                event_codes,
                                cpe_id,
                            )
                            return True
                    else:
                        _LOGGER.info("Found Inform from CPE %s", cpe_id)
                        return True

        except Exception as e:  # noqa: BLE001
            _LOGGER.debug("Error checking logs (attempt %d): %s", attempt, e)

        time.sleep(poll_interval)

    msg = f"CPE {cpe_id} did not send Inform message within {timeout}s"
    raise UseCaseFailure(msg)


def wait_for_reboot_rpc(
    acs: ACS,
    cpe_id: str,
    since: datetime | None = None,
    timeout: int = 90,
) -> datetime | None:
    """Wait for Reboot RPC in ACS CWMP logs.

    .. hint:: This Use Case implements statements from the test suite such as:

        - The ACS responds to the Inform message by issuing the Reboot RPC
        - Verify ACS sent Reboot RPC to CPE

    :param acs: ACS device instance
    :type acs: ACS
    :param cpe_id: CPE identifier
    :type cpe_id: str
    :param since: Only consider logs after this timestamp
    :type since: datetime | None
    :param timeout: Maximum wait time in seconds
    :type timeout: int
    :return: Timestamp when Reboot RPC was sent, or None if not found
    :rtype: datetime | None
    :raises UseCaseFailure: If Reboot RPC not found within timeout
    """
    _LOGGER.info("Waiting for Reboot RPC to CPE %s...", cpe_id)

    poll_interval = 5
    max_attempts = timeout // poll_interval

    for attempt in range(max_attempts):
        try:
            acs_console = acs.console
            logs = acs_console.execute_command(
                f"tail -n 2000 {_GENIEACS_CWMP_LOG}",
                timeout=15,
            )

            log_lines = [line for line in logs.split("\n") if line.strip()]
            log_lines = _filter_logs_by_timestamp(log_lines, since)
            log_lines = _filter_logs_by_cpe_id(log_lines, cpe_id)

            # Look for Reboot RPC: ACS request; acsRequestName="Reboot"
            for line in log_lines:
                line_lower = line.lower()
                if "acs request" in line_lower and "reboot" in line_lower:
                    # Verify it's actually a Reboot RPC
                    if (
                        'acsrequestname="reboot"' in line_lower
                        or "acsrequestname='reboot'" in line_lower
                    ):
                        timestamp = _parse_log_timestamp(line)
                        _LOGGER.info(
                            "Found Reboot RPC to CPE %s at %s", cpe_id, timestamp
                        )
                        return timestamp

        except Exception as e:  # noqa: BLE001
            _LOGGER.debug("Error checking logs (attempt %d): %s", attempt, e)

        if attempt > 0 and attempt % 3 == 0:
            _LOGGER.info(
                "Still waiting for Reboot RPC... (attempt %d/%d)",
                attempt + 1,
                max_attempts,
            )
        time.sleep(poll_interval)

    msg = f"ACS did not issue Reboot RPC to CPE {cpe_id} within {timeout}s"
    raise UseCaseFailure(msg)


def wait_for_boot_inform(
    acs: ACS,
    cpe_id: str,
    since: datetime | None = None,
    timeout: int = 240,
) -> datetime | None:
    """Wait for post-reboot Inform message with boot event codes.

    Verifies reboot completion by checking for Inform message with
    event codes "1 BOOT" and "M Reboot" that appear AFTER the Reboot RPC.

    .. hint:: This Use Case implements statements from the test suite such as:

        - After completing the boot sequence, the CPE sends an Inform message
          to the ACS indicating that the boot sequence has been completed

    :param acs: ACS device instance
    :type acs: ACS
    :param cpe_id: CPE identifier
    :type cpe_id: str
    :param since: Only consider logs after this timestamp
        (typically Reboot RPC time)
    :type since: datetime | None
    :param timeout: Maximum wait time in seconds
    :type timeout: int
    :return: Timestamp of the boot Inform, or None if not found
    :rtype: datetime | None
    :raises UseCaseFailure: If boot Inform not found within timeout
    """
    _LOGGER.info("Waiting for boot Inform from CPE %s...", cpe_id)

    poll_interval = 2
    max_attempts = timeout // poll_interval

    for attempt in range(max_attempts):
        try:
            acs_console = acs.console
            logs = acs_console.execute_command(
                f"tail -n 500 {_GENIEACS_CWMP_LOG}",
                timeout=10,
            )

            log_lines = [line for line in logs.split("\n") if line.strip()]
            log_lines = _filter_logs_by_timestamp(log_lines, since)
            log_lines = _filter_logs_by_cpe_id(log_lines, cpe_id)

            # Look for Inform with "M Reboot" event code
            for line in log_lines:
                if "inform" in line.lower() and "M Reboot" in line:
                    timestamp = _parse_log_timestamp(line)
                    # Verify it's after the since timestamp
                    if since is None or (timestamp and timestamp > since):
                        _LOGGER.info(
                            "Found boot Inform from CPE %s at %s", cpe_id, timestamp
                        )
                        return timestamp

        except Exception as e:  # noqa: BLE001
            _LOGGER.debug("Error checking logs (attempt %d): %s", attempt, e)

        if attempt % 10 == 0 and attempt > 0:
            _LOGGER.info(
                "Still waiting for boot Inform... (attempt %d/%d)",
                attempt + 1,
                max_attempts,
            )
        time.sleep(poll_interval)

    msg = f"CPE {cpe_id} did not send boot Inform within {timeout}s"
    raise UseCaseFailure(msg)


def is_cpe_online(
    acs: ACS,
    cpe: CPE,
    timeout: int = 30,
    via: InterfaceType = "nbi",
) -> bool:
    """Check if CPE is online and responding via ACS.

    .. hint:: This Use Case implements statements from the test suite such as:

        - Verify CPE is online and reachable via ACS
        - The CPE is online

    :param acs: ACS device instance
    :type acs: ACS
    :param cpe: CPE device instance
    :type cpe: CPE
    :param timeout: Query timeout in seconds
    :type timeout: int
    :param via: Interface to use ("nbi" for API, "gui" for web interface)
    :type via: InterfaceType
    :return: True if CPE responds
    :rtype: bool
    """
    try:
        # Try to get a simple parameter to verify CPE is online
        result = get_parameter_value(
            acs,
            cpe,
            "Device.DeviceInfo.SoftwareVersion",
            timeout=timeout,
            retries=2,
            via=via,
        )
        return bool(result)
    except (UseCaseFailure, Exception):  # noqa: BLE001
        return False


def send_connection_request(
    acs: ACS,
    cpe: CPE,
) -> bool:
    """Send connection request to CPE via ACS.

    The connection request triggers the CPE to initiate a TR-069 session
    with the ACS.

    .. hint:: This Use Case implements statements from the test suite such as:

        - The ACS sends a connection request to the CPE

    :param acs: ACS device instance
    :type acs: ACS
    :param cpe: CPE device instance
    :type cpe: CPE
    :return: True if connection request sent successfully
    :rtype: bool
    """
    # Connection request is typically triggered by creating a task
    # with connection_request=True. Reboot method does this automatically.
    # For explicit connection request, we can use ScheduleInform
    cpe_id = cpe.sw.cpe_id
    try:
        acs.nbi.ScheduleInform(
            CommandKey="conn_request", DelaySeconds=0, cpe_id=cpe_id
        )
        return True
    except Exception as e:  # noqa: BLE001
        _LOGGER.warning("Failed to send connection request: %s", e)
        return False


def verify_queued_task(
    acs: ACS,
    cpe_id: str,
    task_type: str = "reboot",
    since: datetime | None = None,
) -> bool:
    """Verify a task is queued for the CPE in GenieACS.

    .. hint:: This Use Case implements statements from the test suite such as:

        - The ACS queues the Reboot RPC as a pending task

    :param acs: ACS device instance
    :type acs: ACS
    :param cpe_id: CPE identifier
    :type cpe_id: str
    :param task_type: Type of task to look for (e.g., "reboot")
    :type task_type: str
    :param since: Only consider logs after this timestamp
    :type since: datetime | None
    :return: True if task is queued
    :rtype: bool
    """
    try:
        acs_console = acs.console
        logs = acs_console.execute_command(
            f"tail -n 100 {_GENIEACS_NBI_LOG}",
            timeout=15,
        )

        log_lines = [line for line in logs.split("\n") if line.strip()]
        log_lines = _filter_logs_by_timestamp(log_lines, since)
        log_lines = _filter_logs_by_cpe_id(log_lines, cpe_id)

        for line in log_lines:
            if task_type.lower() in line.lower():
                _LOGGER.info("Found queued %s task for CPE %s", task_type, cpe_id)
                return True

        return False

    except Exception as e:  # noqa: BLE001
        _LOGGER.warning("Could not verify queued task: %s", e)
        return False
