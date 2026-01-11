"""RPi prplOS based CPE device class."""

from __future__ import annotations

import json
import logging
import re
from functools import cached_property
from ipaddress import AddressValueError, IPv4Address
from time import sleep
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import jc
import pexpect

from boardfarm3 import hookimpl
from boardfarm3.devices.base_devices.boardfarm_device import BoardfarmDevice
from boardfarm3.exceptions import (
    ConfigurationFailure,
    DeviceBootFailure,
    DeviceNotFound,
    NotSupportedError,
)
from boardfarm3.lib.connection_factory import connection_factory
from boardfarm3.lib.cpe_sw import CPESwLibraries
from boardfarm3.lib.utils import retry
from boardfarm3.templates.acs import ACS
from boardfarm3.templates.cpe import CPE, CPEHW
from boardfarm3.templates.provisioner import Provisioner

if TYPE_CHECKING:
    from argparse import Namespace

    from boardfarm3.lib.boardfarm_pexpect import BoardfarmPexpect
    from boardfarm3.lib.device_manager import DeviceManager
    from boardfarm3.lib.hal.cpe_wifi import WiFiHal
    from boardfarm3.templates.cpe.cpe_hw import TerminationSystem
    from boardfarm3.templates.tftp import TFTP

_LOGGER = logging.getLogger(__name__)


class RPiPrplOSHW(CPEHW):
    """RPi prplOS hardware device class."""

    def __init__(self, config: dict[str, Any], cmdline_args: Namespace) -> None:
        """Initialize CPE hardware.

        :param config: CPE config
        :param cmdline_args: command line arguments
        """
        self._config = config
        self._cmdline_args = cmdline_args
        self._console: BoardfarmPexpect = None

    @property
    def config(self) -> dict[str, Any]:
        """Device config.

        :return: Device config
        :rtype: dict[str, Any]
        """
        return self._config

    @property
    def mac_address(self) -> str:
        """Get CPE MAC address.

        :return: MAC address
        :rtype: str
        """
        # First try to get from config
        if mac := self._config.get("mac"):
            return mac

        # If console is available, try reading from /var/etc/environment first
        # (populated by set-mac-address.sh which reads from eth1)
        # If that's not available yet, fall back to reading directly from eth1
        if self._console:
            # First try: read from /var/etc/environment
            try:
                output = self._console.execute_command(
                    "grep HWMACADDRESS /var/etc/environment 2>/dev/null || echo ''"
                )
                if output and "HWMACADDRESS" in output:
                    mac = re.findall('"([^"]*)"', output).pop()
                    if mac and len(mac) == 17:  # Valid MAC format
                        return mac
            except (ValueError, AttributeError, IndexError):
                pass

            # Fallback: read directly from eth1 interface
            try:
                output = self._console.execute_command(
                    "cat /sys/class/net/eth1/address 2>/dev/null || echo ''"
                )
                mac = output.strip()
                if mac and len(mac) == 17:  # Valid MAC format: XX:XX:XX:XX:XX:XX
                    return mac.lower()
            except (ValueError, AttributeError, OSError):
                pass

        msg = (
            "Failed to get mac address from config, eth1 interface, "
            "or /var/etc/environment"
        )
        raise ValueError(msg)

    @property
    def serial_number(self) -> str:
        """Get CPE Serial number.

        :return: Serial number
        :rtype: str
        """
        if self._console:
            output = self._console.execute_command(
                "grep Serial /proc/cpuinfo |awk '{print $3}'"
            )
            return output.strip()

        return self._config.get("serial")

    @property
    def wan_iface(self) -> str:
        """WAN interface name.

        :return: the wan interface name
        :rtype: str
        """
        return "eth1"

    @property
    def mta_iface(self) -> str:
        """MTA interface name.

        :raises NotSupportedError: voice is not enabled
        """
        raise NotSupportedError

    @property
    def _shell_prompt(self) -> list[str]:
        """Console prompt.

        :return: the shell prompt
        :rtype: list[str]
        """
        return [r"root@prplOS:.*#"]

    def connect_to_consoles(self, device_name: str) -> None:
        """Establish connection to the device console.

        :param device_name: device name
        :type device_name: str
        """
        self._console = connection_factory(
            connection_type=str(self._config.get("connection_type")),
            connection_name=f"{device_name}.console",
            conn_command=self._config["conn_cmd"][0],
            save_console_logs=self._cmdline_args.save_console_logs,
            shell_prompt=self._shell_prompt,
        )
        self._console.timeout = 120
        
        # 1. Start console (done by connection_factory)
        # 2. Wait for 'Terminal ready'
        try:
            self._console.expect("Terminal ready", timeout=5)
            _LOGGER.debug("Picocom: Terminal ready detected")
        except pexpect.TIMEOUT:
            _LOGGER.warning("Picocom: Terminal ready not detected (might have missed it)")

        # 3. Press 'Enter'
        self._console.sendline("")
        
        # 5. Wait for 'Please press Enter to activate this console.'
        # OR wait for prompt if device is already active
        _LOGGER.info("Connecting to console... waiting for prompt or activation message")
        
        max_retries = 30
        for i in range(max_retries):
            try:
                # Wait for either prompt or activation message
                index = self._console.expect(
                    self._shell_prompt + ["Please press Enter to activate this console"],
                    timeout=10
                )
                
                if index < len(self._shell_prompt):
                    # Matched a shell prompt - we are good!
                    _LOGGER.debug("Console active (prompt matched)")
                    break
                else:
                    # 5. Wait for 'Please press Enter...' (Matched)
                    # 6. Press 'Enter'
                    _LOGGER.debug("Found activation message, pressing Enter")
                    self._console.sendline("")
                    
                    # After pressing enter, we should get a prompt immediately
                    try:
                        self._console.expect(self._shell_prompt, timeout=5)
                        _LOGGER.debug("Console activated (prompt matched)")
                        break
                    except pexpect.TIMEOUT:
                        # If prompt doesn't appear immediately, continue loop
                        continue
                        
            except pexpect.TIMEOUT:
                _LOGGER.debug("Timeout waiting for console output (attempt %d/%d)", i + 1, max_retries)
                # Just continue waiting
                continue
                
        # Send newline to ensure prompt is fresh for login_to_server
        self._console.sendline("")
        self._console.login_to_server()

    def get_console(self, console_name: str) -> BoardfarmPexpect:
        """Return console instance with the given name.

        :param console_name: name of the console
        :type console_name: str
        :raises ValueError: on unknown console name
        :return: console instance with given name
        :rtype: BoardfarmPexpect
        """
        if console_name == "console":
            return self._console
        msg = f"Unknown console name: {console_name}"
        raise ValueError(msg)

    def disconnect_from_consoles(self) -> None:
        """Disconnect/Close the console connections."""
        if self._console is not None:
            self._console.close()

    def get_interactive_consoles(self) -> dict[str, BoardfarmPexpect]:
        """Get interactive consoles of the device.

        :returns: device interactive consoles
        """
        return {"console": self._console}

    def power_cycle(self) -> None:
        """Power cycle the CPE via cli."""
        # Ensure we have control before rebooting
        self._console.sendline("")
        try:
            self._console.expect(self._shell_prompt, timeout=5)
        except pexpect.TIMEOUT:
            # Try to activate if we timed out
            self._console.sendline("")
            
        _LOGGER.info("Sending reboot command")
        self._console.sendline("reboot")
        
        # Wait for reboot to actually start (device goes down)
        # sleep for 20s to ensure device shuts down and starts booting
        sleep(20)
        
        self.disconnect_from_consoles()
        self.connect_to_consoles("board")

    def flash_via_bootloader(
        self,
        image: str,  # noqa: ARG002
        tftp_devices: dict[str, TFTP],  # noqa: ARG002
        termination_sys: TerminationSystem = None,  # noqa: ARG002
        method: str | None = None,  # noqa: ARG002
    ) -> None:
        """Flash cpe via the bootloader.

        :param image: image name
        :type image: str
        :param tftp_devices: a list of LAN side TFTP devices
        :type tftp_devices: dict[str, TFTP]
        :param termination_sys: the termination system device
        :type termination_sys: TerminationSystem
        :param method: flash method, defaults to None
        :type method: str, optional
        :raises NotSupportedError: cannot be flashed via bootloader
        """
        raise NotSupportedError

    def wait_for_hw_boot(self) -> None:
        """Wait for CPE to have WAN interface added.

        :raises DeviceBootFailure: if CPE is unable to bring up WAN interface
        """
        for i in range(20):
            try:
                self._console.sendline("ip addr show dev eth1")
                self._console.expect(self._shell_prompt, timeout=5)
                # Parse output manually to be safe
                output = self._console.before
                if isinstance(output, bytes):
                    output = output.decode("utf-8", errors="ignore")
                
                _LOGGER.debug("ip addr show output (attempt %d): %r", i, output)
                
                if self.wan_iface in output and "inet " in output:
                    return
            except Exception as e:
                _LOGGER.debug("Error checking WAN: %s", e)
            
            sleep(5)
        
        msg = f"CPE failed to bring up WAN interface: {self.wan_iface}"
        raise DeviceBootFailure(msg)


class RPiPrplOSSW(CPESwLibraries):
    """RPi prplOS software component device class."""

    _hw: RPiPrplOSHW

    def __init__(self, hardware: RPiPrplOSHW) -> None:
        """Initialise the RPiPrplOS sofware class.

        :param hardware: the board hw object
        :type hardware: RPiPrplOSHW
        """
        super().__init__(hardware)

    @property
    def wifi(self) -> WiFiHal:
        """Return instance of WiFi component.

        :raises NotSupportedError: WiFi is not enabled yet
        """
        raise NotSupportedError

    @property
    def version(self) -> str:
        """CPE software version.

        :return: version
        :rtype: str
        """
        return self._console.execute_command("cat /etc/build.prplos.version")

    @property
    def erouter_iface(self) -> str:
        """E-Router interface name.

        :return: E-Router interface name
        :rtype: str
        """
        return "eth1"

    @property
    def lan_iface(self) -> str:
        """LAN interface name.

        :return: LAN interface name
        :rtype: str
        """
        return "br-lan"

    @property
    def guest_iface(self) -> str:
        """Guest network interface name.

        :return: name of the guest network interface
        :rtype: str
        """
        return "br-guest"

    @property
    def json_values(self) -> dict[str, Any]:
        """CPE Specific JSON values.

        :return: the CPE Specific JSON values
        :rtype: dict[str, Any]
        """
        json: dict[str, str] = {}

        # Return the default UCI output
        uci_output = self._console.execute_command("uci show").splitlines()
        for line in uci_output:
            if "=" in line:
                k, v = line.strip().split("=")
                json[k] = v
        return json

    @property
    def gui_password(self) -> str:
        """GUI login password.

        :return: GUI password
        :rtype: str
        """
        return self._hw.config.get("gui_password", "admin")

    @cached_property
    def cpe_id(self) -> str:
        """TR069 CPE ID in format OUI-ProductClass-SerialNumber.

        This matches the format icwmpd reports to the ACS in the Inform message.
        The CPE ID is constructed from device identity values (eth1 MAC for OUI,
        /proc/cpuinfo for SerialNumber, fixed ProductClass).
        
        Note: ProductClass uses no special characters (e.g., 'RPi4prplOS') to
        avoid URL encoding issues when GenieACS stores the device _id.

        :return: CPE ID
        :rtype: str
        """
        oui, product_class, serial = self._get_device_identity()
        cpe_id = f"{oui}-{product_class}-{serial}"
        _LOGGER.info("TR-069 CPE ID: %s", cpe_id)
        return cpe_id

    @property
    def tr69_cpe_id(self) -> str:
        """TR-69 CPE Identifier.

        :return: TR069 CPE ID
        :rtype: str
        """
        return self.cpe_id

    @property
    def lan_gateway_ipv4(self) -> IPv4Address:
        """LAN Gateway IPv4 address.

        :return: the ip (if present) 255.255.255.255 otherwise
        :rtype: IPv4Address
        """
        console = self._get_console("default_shell")
        try:
            return IPv4Address(
                console.execute_command(
                    "ifconfig br-lan|grep 'inet addr:' | tr ':' ' '| awk '{print $3}'"
                )
            )

        except AddressValueError:
            return IPv4Address("255.255.255.255")

    def is_production(self) -> bool:
        """Is production software.

        :return: Production status
        :rtype: bool
        """
        return False

    def reset(self, method: str | None = None) -> None:  # noqa: ARG002
        """Perform a reset via given method.

        :param method: reset method(sw/hw)
        """
        self._hw.power_cycle()

    def factory_reset(self, method: str | None = None) -> bool:  # noqa: ARG002
        """Perform factory reset CPE via given method.

        :param method: factory reset method. Default None.
        :type method: str | None
        :raises NotSupportedError: Not supported yet.
        """
        raise NotSupportedError

    def wait_for_boot(self) -> None:
        """Wait for CPE to boot."""
        self._hw.wait_for_hw_boot()

    def get_provision_mode(self) -> str:
        """Return provision mode.

        :return: the provisioning mode
        :rtype: str
        """
        return self._hw.config.get("eRouter_Provisioning_mode", "dual")

    def verify_cpe_is_booting(self) -> None:
        """Verify CPE is booting.

        :raises NotSupportedError: not implemented
        """
        raise NotSupportedError

    def _is_tr181_ready(self) -> bool:
        """Check if TR-181 data model is accessible via ubus (bbfdm).

        :return: True if TR-181 is ready, False otherwise
        :rtype: bool
        """
        try:
            console = self._get_console("default_shell")
            prompt = self._hw._shell_prompt
            
            # Check if bbfdm ubus object exists and responds
            console.sendline("ubus call bbfdm get '{\"path\":\"Device.DeviceInfo.Manufacturer\"}'")
            console.expect(prompt, timeout=10)
            output = console.before
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="ignore")
            
            # If we get a valid response (not "Command failed"), TR-181 is ready
            if "Command failed" not in output and "Not found" not in output:
                return True
            return False
        except (pexpect.TIMEOUT, pexpect.EOF, AttributeError, ValueError, OSError):
            return False

    def wait_device_online(self) -> None:
        """Wait for WAN interface to come online and TR-181 to be ready.

        :raises DeviceBootFailure: if board is not online or TR-181 not ready
        """
        # First wait for network to come online
        network_online = False
        for _ in range(20):
            if self.is_online():
                network_online = True
                break
            sleep(20)
        
        if not network_online:
            msg = "Board not online"
            raise DeviceBootFailure(msg)
        
        # Once network is online, wait for TR-181 to be ready
        _LOGGER.debug("Network is online, waiting for TR-181 to be ready")
        for attempt in range(30):  # Wait up to 30 * 5 = 150 seconds
            if self._is_tr181_ready():
                _LOGGER.debug("TR-181 is ready")
                return
            if attempt < 29:
                _LOGGER.debug(
                    "TR-181 not ready yet (attempt %d/30), waiting...",
                    attempt + 1,
                )
                sleep(5)
        
        msg = "TR-181 not ready after network came online"
        raise DeviceBootFailure(msg)

    def _get_device_identity(self) -> tuple[str, str, str]:
        """Get device identity values for TR-069.

        Calculates OUI, ProductClass, and SerialNumber for the RPi.
        This mirrors the approach used in the docker prplOS implementation.

        :return: Tuple of (OUI, ProductClass, SerialNumber)
        :rtype: tuple[str, str, str]
        """
        console = self._get_console("default_shell")
        
        oui = ""
        # ProductClass without special characters to avoid URL encoding in ACS
        # This ensures Boardfarm cpe_id matches GenieACS device _id exactly
        product_class = "RPi4prplOS"
        serial = ""
        
        # Get OUI from eth1 MAC address (first 3 octets, uppercase, no colons)
        try:
            mac = console.execute_command(
                "cat /sys/class/net/eth1/address 2>/dev/null || echo ''"
            ).strip()
            if mac and len(mac) >= 8:
                # OUI is first 3 octets without colons, uppercase
                oui = mac[:8].replace(":", "").upper()
                _LOGGER.debug("OUI from eth1 MAC: %s", oui)
        except (pexpect.TIMEOUT, AttributeError, ValueError) as e:
            _LOGGER.warning("Failed to get OUI from eth1: %s", e)
            oui = "000000"
        
        # Get SerialNumber from RPi /proc/cpuinfo
        try:
            serial = console.execute_command(
                "grep Serial /proc/cpuinfo | awk '{print $3}'"
            ).strip()
            _LOGGER.debug("Serial from /proc/cpuinfo: %s", serial)
        except (pexpect.TIMEOUT, AttributeError, ValueError) as e:
            _LOGGER.warning("Failed to get serial from /proc/cpuinfo: %s", e)
            serial = "unknown"
        
        return oui, product_class, serial

    def _configure_device_identity(self) -> None:
        """Configure device identity for TR-069 via UCI cwmp.cpe section.

        This is critical for TR-069 to work correctly. The sysmngr service
        (which provides Device.DeviceInfo.* values to bbfdm) reads device
        identity values from UCI cwmp.cpe options FIRST, then falls back
        to the db database. Since the db database is not populated by default
        on RPi prplOS, we MUST configure the UCI options.

        The sysmngr deviceinfo.c code shows:
        - Device.DeviceInfo.Manufacturer <- cwmp.cpe.manufacturer || db
        - Device.DeviceInfo.ManufacturerOUI <- cwmp.cpe.manufacturer_oui || db
        - Device.DeviceInfo.ProductClass <- cwmp.cpe.product_class || db
        - Device.DeviceInfo.SerialNumber <- cwmp.cpe.serial_number || db
        - Device.DeviceInfo.ModelName <- cwmp.cpe.model_name || db

        After configuring UCI, we restart sysmngr (which runs as dm_sysmngr)
        to pick up the new values.

        :return: The constructed CPE ID (OUI-ProductClass-SerialNumber)
        :rtype: str
        """
        console = self._get_console("default_shell")
        prompt = self._hw._shell_prompt
        
        # Get device identity values
        oui, product_class, serial = self._get_device_identity()
        
        _LOGGER.info(
            "Configuring device identity via UCI cwmp.cpe: "
            "OUI=%s, ProductClass=%s, Serial=%s",
            oui, product_class, serial
        )
        
        # Get software version for icwmpd
        # NOTE: Using sendline/expect instead of execute_command to avoid
        # timeout issues with serial console line wrapping
        sw_version = "unknown"
        try:
            console.sendline("cat /etc/openwrt_version")
            console.expect(prompt, timeout=10)
            output = console.before
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="ignore")
            # Extract version from output (last non-empty line before prompt)
            lines = [l.strip() for l in output.split('\n') if l.strip()]
            if lines:
                # Skip the command echo, get the actual output
                for line in lines[1:]:
                    if line and not line.startswith('root@') and not line.startswith('cat '):
                        sw_version = line
                        break
            _LOGGER.debug("Software version: %s", sw_version)
        except pexpect.TIMEOUT:
            _LOGGER.warning("Timeout getting software version, using 'unknown'")
        
        # Get WAN interface device name (e.g., 'eth1')
        wan_iface = self._hw.wan_iface
        
        # Configure device identity in cwmp.cpe UCI section
        # This is where sysmngr reads the values from (see deviceinfo.c)
        # CRITICAL: cwmp.cpe.interface must be set to the actual device name
        # (e.g., 'eth1'), NOT the netifd interface name (e.g., 'wan').
        # This is required for icwmpd to determine the ConnectionRequestURL.
        #
        # NOTE: product_class uses no special characters (e.g., 'RPi4prplOS')
        # to avoid URL encoding issues when GenieACS stores the device _id.
        uci_cmds = [
            'uci set cwmp.cpe.manufacturer="prpl Foundation"',
            f'uci set cwmp.cpe.manufacturer_oui="{oui}"',
            f'uci set cwmp.cpe.product_class="{product_class}"',
            f'uci set cwmp.cpe.serial_number="{serial}"',
            f'uci set cwmp.cpe.model_name="{product_class}"',
            f'uci set cwmp.cpe.software_version="{sw_version}"',
            # Set interface to actual device name for ConnectionRequestURL
            f'uci set cwmp.cpe.interface="{wan_iface}"',
            'uci commit cwmp',
        ]
        
        for cmd in uci_cmds:
            console.sendline(cmd)
            console.expect(prompt, timeout=5)
        
        _LOGGER.debug("UCI cwmp.cpe device identity configured")
        
        # Verify UCI configuration
        console.sendline("uci show cwmp.cpe | grep -E 'manufacturer|serial|product'")
        console.expect(prompt, timeout=5)
        output = console.before
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="ignore")
        _LOGGER.debug("UCI cwmp.cpe config: %s", output)
        
        # Restart sysmngr service to pick up the new UCI values
        # sysmngr runs as dm_sysmngr and provides Device.DeviceInfo.* to bbfdm
        _LOGGER.info("Restarting sysmngr to apply device identity from UCI")
        console.sendline("/etc/init.d/sysmngr restart 2>/dev/null || true")
        console.expect(prompt, timeout=15)
        
        # Wait for sysmngr to reinitialize
        sleep(5)
        
        # Send empty line to ensure clean buffer before verification
        console.sendline("")
        console.expect(prompt, timeout=5)
        
        # Verify the values are now in bbfdm
        _LOGGER.debug("Verifying device identity in bbfdm after sysmngr restart")
        console.sendline('ubus call bbfdm get \'{"path": "Device.DeviceInfo.ManufacturerOUI"}\'')
        console.expect(prompt, timeout=10)
        
        console.sendline('ubus call bbfdm get \'{"path": "Device.DeviceInfo.SerialNumber"}\'')
        console.expect(prompt, timeout=10)
        
        # Log the configured identity (note: Boardfarm cpe_id uses OUI-Serial only)
        _LOGGER.info(
            "Device identity configured via UCI: OUI=%s, ProductClass=%s, Serial=%s",
            oui, product_class, serial
        )

    def _configure_via_uci(self, url: str, username: str, password: str) -> None:
        """Configure ACS using UCI for icwmp (iopsys TR-069 client).

        :param url: ACS URL
        :param username: ACS username
        :param password: ACS password
        """
        console = self._get_console("default_shell")
        prompt = self._hw._shell_prompt
        
        # Check for cwmp UCI package (used by icwmp)
        console.sendline("uci show cwmp 2>&1")
        console.expect(prompt)
        output = console.before
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="ignore")
        
        if "Entry not found" not in output:
            _LOGGER.info("Configuring icwmp via UCI cwmp package")
            
            # icwmp uses cwmp.acs section for ACS configuration
            # Also set the WAN interface to eth1 (critical for RPi!)
            cmds = [
                f'uci set cwmp.acs.url="{url}"',
                f'uci set cwmp.acs.periodic_inform_enable="1"',
                f'uci set cwmp.acs.periodic_inform_interval="300"',
                'uci set cwmp.cpe.default_wan_interface="eth1"',  # Critical for RPi
            ]
            
            if username:
                cmds.append(f'uci set cwmp.acs.username="{username}"')
            if password:
                cmds.append(f'uci set cwmp.acs.password="{password}"')
            
            cmds.append('uci commit cwmp')
            
            for cmd in cmds:
                console.sendline(cmd)
                console.expect(prompt)
            
            # Restart icwmpd service
            _LOGGER.info("Restarting icwmpd service")
            console.sendline("/etc/init.d/icwmpd restart")
            console.expect(prompt, timeout=15)
            return
        
        # Fallback: check if obuspa is available (USP mode)
        console.sendline("uci show obuspa 2>&1")
        console.expect(prompt)
        output = console.before
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="ignore")
        
        if "Entry not found" not in output:
            _LOGGER.warning(
                "obuspa UCI config found but this is for USP/TR-369, not TR-069. "
                "icwmp UCI package (cwmp) not found."
            )
        
        msg = "Failed to configure ACS: cwmp UCI package not found (icwmp not installed?)"
        raise DeviceBootFailure(msg)

    def configure_management_server(
        self, url: str, username: str | None = "", password: str | None = ""
    ) -> None:
        """Configure TR-069 ACS connection using bbfdm or UCI.

        This method configures the icwmp TR-069 client to connect to the ACS.
        It first configures the device identity (OUI, ProductClass, SerialNumber)
        in bbfdm, then sets the ACS URL and other parameters.

        The device identity configuration is critical because icwmpd uses these
        values when sending Inform messages to the ACS. Without proper identity,
        the ACS will not recognize the device with the expected CPE ID.

        :param url: Management Server URL (e.g., http://172.25.1.40:7547)
        :type url: str
        :param username: CWMP client username, defaults to ""
        :type username: str | None, optional
        :param password: CWMP client password, defaults to ""
        :type password: str | None, optional
        :raises DeviceBootFailure: if TR-181 is not accessible
        """
        # Ensure TR-181 (bbfdm) is ready before attempting configuration
        _LOGGER.info("Checking TR-181 (bbfdm) readiness before configuring ACS")
        max_attempts = 15
        for attempt in range(max_attempts):
            if self._is_tr181_ready():
                _LOGGER.info("TR-181 (bbfdm) is ready, proceeding with ACS configuration")
                break
            if attempt < max_attempts - 1:
                _LOGGER.debug(
                    "TR-181 not ready yet (attempt %d/%d), waiting...",
                    attempt + 1,
                    max_attempts,
                )
                sleep(3)
        else:
            msg = "TR-181 data model (bbfdm) not accessible after 15 attempts"
            _LOGGER.error(msg)
            # Dump ubus list for debugging
            try:
                prompt = self._hw._shell_prompt
                console = self._get_console("default_shell")
                console.sendline("ubus list | grep -E 'bbf|cwmp|icwmp'")
                console.expect(prompt, timeout=5)
                _LOGGER.error("ubus list (filtered): %s", console.before)
            except Exception:
                pass
            raise DeviceBootFailure(msg)

        console = self._get_console("default_shell")
        prompt = self._hw._shell_prompt
        
        # CRITICAL: Configure device identity FIRST
        # This ensures icwmpd uses the correct OUI, ProductClass, SerialNumber
        # when sending Inform messages to the ACS. Without this, the ACS will
        # register the device with empty/different identity values.
        _LOGGER.info("Configuring device identity before ACS setup")
        self._configure_device_identity()
        
        # Configure WAN interface in UCI (critical for RPi where WAN is eth1)
        _LOGGER.info("Configuring WAN interface for icwmp")
        console.sendline('uci set cwmp.cpe.default_wan_interface="eth1"')
        console.expect(prompt, timeout=5)
        console.sendline('uci commit cwmp')
        console.expect(prompt, timeout=5)
        
        # Try to configure via bbfdm ubus interface first
        _LOGGER.info("Configuring ACS URL via bbfdm: %s", url)
        cmd = f'ubus call bbfdm set \'{{"path": "Device.ManagementServer.URL", "value": "{url}"}}\''
        console.sendline(cmd)
        console.expect(prompt, timeout=10)
        
        output = console.before
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="ignore")
        
        # Check if bbfdm set worked
        if "Command failed" in output or "error" in output.lower():
            _LOGGER.warning("bbfdm ubus set failed, falling back to UCI: %s", output)
            self._configure_via_uci(url, username or "", password or "")
            return
        
        _LOGGER.debug("ACS URL configured via bbfdm")
        
        # Configure Username via bbfdm
        if username:
            cmd = f'ubus call bbfdm set \'{{"path": "Device.ManagementServer.Username", "value": "{username}"}}\''
            console.sendline(cmd)
            console.expect(prompt, timeout=10)

        # Configure Password via bbfdm
        if password:
            cmd = f'ubus call bbfdm set \'{{"path": "Device.ManagementServer.Password", "value": "{password}"}}\''
            console.sendline(cmd)
            console.expect(prompt, timeout=10)

        # Enable periodic inform
        console.sendline('ubus call bbfdm set \'{"path": "Device.ManagementServer.PeriodicInformEnable", "value": "true"}\'')
        console.expect(prompt, timeout=10)
        
        console.sendline('ubus call bbfdm set \'{"path": "Device.ManagementServer.PeriodicInformInterval", "value": "300"}\'')
        console.expect(prompt, timeout=10)

        # Ensure WAN interface is up
        _LOGGER.debug("Ensuring WAN interface is up")
        console.sendline("ubus call network.interface.wan up 2>/dev/null || true")
        console.expect(prompt, timeout=5)
        
        # Commit any UCI changes made by bbfdm
        console.sendline("uci commit cwmp")
        console.expect(prompt, timeout=5)
        
        # Restart icwmpd to apply changes (including device identity)
        _LOGGER.info("Restarting icwmpd service to apply ACS configuration and device identity")
        sleep(2)
        console.sendline("/etc/init.d/icwmpd restart")
        console.expect(prompt, timeout=15)
        
        # Give icwmpd time to initialize and send Inform
        _LOGGER.info("Waiting for icwmpd to initialize...")
        sleep(8)
        
        # Verify icwmpd is running and check key parameters
        console.sendline("ps | grep icwmp")
        console.expect(prompt, timeout=5)
        output = console.before
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="ignore")
        _LOGGER.debug("icwmpd process check: %s", output)
        
        # Check ConnectionRequestURL (must have valid IP)
        console.sendline('ubus call bbfdm get \'{"path": "Device.ManagementServer.ConnectionRequestURL"}\'')
        console.expect(prompt, timeout=10)
        output = console.before
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="ignore")
        _LOGGER.info("ConnectionRequestURL: %s", output)
        
        # Check ACS URL
        console.sendline('ubus call bbfdm get \'{"path": "Device.ManagementServer.URL"}\'')
        console.expect(prompt, timeout=10)
        output = console.before
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="ignore")
        _LOGGER.debug("ACS URL in bbfdm: %s", output)

    def wait_for_acs_connection(
        self, acs: ACS, timeout: int = 120
    ) -> None:
        """Wait for CPE to connect to ACS.

        :param acs: ACS device instance
        :type acs: ACS
        :param timeout: Maximum time to wait in seconds, defaults to 120
        :type timeout: int, optional
        :raises DeviceBootFailure: if CPE does not connect within timeout
        """
        _LOGGER.info(
            "Waiting for CPE %s to connect to ACS (timeout: %ds)",
            self.cpe_id,
            timeout,
        )
        # icwmpd needs time to:
        # 1. Read UCI configuration
        # 2. Query bbfdm for Device.DeviceInfo.* parameters
        # 3. Establish connection to ACS
        # 4. Send initial Inform message
        _LOGGER.debug("Waiting 15 seconds for CWMP client to initialize...")
        sleep(15)
        
        # Extract OUI and SerialNumber for ACS query
        # GenieACS stores device ID with URL-encoded characters (e.g., %2D for -)
        # So we query by _deviceId fields instead of _id
        oui, product_class, serial = self._get_device_identity()
        
        max_attempts = (timeout - 15) // 5
        for attempt in range(max_attempts):
            try:
                # First try to get all devices to verify API connectivity
                # Access _request_get via acs.nbi (NBI = North Bound Interface)
                response_data = None
                nbi = getattr(acs, "nbi", None)
                if nbi and hasattr(nbi, "_request_get"):
                    try:
                        # Simple query - just get all devices
                        all_devices_url = '/devices'
                        all_response = nbi._request_get(  # noqa: SLF001
                            all_devices_url, timeout=10
                        )
                        if attempt == 0:
                            _LOGGER.debug(
                                "ACS has %d devices registered",
                                len(all_response) if isinstance(all_response, list) else 0
                            )
                            # Log first device ID for debugging
                            if all_response and isinstance(all_response, list) and len(all_response) > 0:
                                first_device = all_response[0]
                                _LOGGER.debug(
                                    "First device _id: %s, _deviceId: %s",
                                    first_device.get("_id"),
                                    first_device.get("_deviceId")
                                )
                        
                        # Search for our device by serial number
                        for device in (all_response or []):
                            device_id = device.get("_deviceId", {})
                            if device_id.get("_SerialNumber") == serial:
                                _LOGGER.info(
                                    "Found device with serial %s in ACS: %s",
                                    serial, device.get("_id")
                                )
                                response_data = [device]
                                break
                        
                    except Exception as req_error:  # noqa: BLE001
                        if attempt == 0:
                            _LOGGER.debug("ACS request failed: %s", req_error)
                else:
                    if attempt == 0:
                        _LOGGER.warning(
                            "ACS device has no nbi._request_get method. "
                            "nbi=%s, has_request_get=%s",
                            nbi, hasattr(nbi, "_request_get") if nbi else "N/A"
                        )

                if (
                    response_data
                    and isinstance(response_data, list)
                    and len(response_data) > 0
                ):
                    _LOGGER.info(
                        "CPE %s registered in ACS, verifying connectivity...",
                        self.cpe_id,
                    )
                    # Device found - get the actual _id from the response for GPV
                    acs_device_id = response_data[0].get("_id", self.cpe_id)
                    _LOGGER.debug("ACS device ID: %s", acs_device_id)
                    try:
                        result = acs.GPV(
                            "Device.DeviceInfo.SerialNumber",
                            cpe_id=acs_device_id,
                            timeout=10,
                        )
                        if result and len(result) > 0:
                            _LOGGER.info(
                                "CPE %s successfully connected to ACS",
                                self.cpe_id,
                            )
                            return
                    except Exception as gpv_error:  # noqa: BLE001
                        _LOGGER.debug(
                            "Device exists but GPV query failed: %s",
                            gpv_error,
                        )
                        # Device is registered even if GPV fails
                        _LOGGER.info(
                            "CPE %s found in ACS (GPV not working yet)",
                            self.cpe_id,
                        )
                        return
                else:
                    _LOGGER.debug(
                        "CPE not yet registered in ACS (attempt %d/%d)",
                        attempt + 1,
                        max_attempts,
                    )
            except Exception as e:  # noqa: BLE001
                error_msg = str(e) or repr(e) or "No error message"
                _LOGGER.debug(
                    "CPE not yet available in ACS (attempt %d/%d): %s: %s",
                    attempt + 1,
                    max_attempts,
                    type(e).__name__,
                    error_msg,
                )
            if attempt < max_attempts - 1:
                sleep(5)

        # Capture diagnostic information before raising failure
        try:
            console = self._get_console("default_shell")
            prompt = self._hw._shell_prompt
            
            _LOGGER.error("CPE failed to connect to ACS. Capturing diagnostics...")
            
            # Check if icwmpd is running
            console.sendline("ps | grep -E 'icwmp|cwmp'")
            console.expect(prompt, timeout=5)
            output = console.before
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="ignore")
            _LOGGER.error("icwmpd process status: %s", output)
            
            # Get recent icwmp log messages
            console.sendline("logread | grep -i icwmp | tail -20")
            console.expect(prompt, timeout=10)
            output = console.before
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="ignore")
            _LOGGER.error("Recent icwmp logs: %s", output)
            
            # Check ConnectionRequestURL
            console.sendline('ubus call bbfdm get \'{"path": "Device.ManagementServer.ConnectionRequestURL"}\'')
            console.expect(prompt, timeout=10)
            output = console.before
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="ignore")
            _LOGGER.error("ConnectionRequestURL: %s", output)
            
            # Check ACS URL
            console.sendline('ubus call bbfdm get \'{"path": "Device.ManagementServer.URL"}\'')
            console.expect(prompt, timeout=10)
            output = console.before
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="ignore")
            _LOGGER.error("ACS URL: %s", output)
            
        except Exception as diag_error:  # noqa: BLE001
            _LOGGER.error("Failed to capture diagnostics: %s", diag_error)
        
        msg = (
            f"CPE {self.cpe_id} did not connect to ACS within "
            f"{timeout} seconds"
        )
        _LOGGER.error(msg)
        raise DeviceBootFailure(msg)

    def finalize_boot(self) -> bool:
        """Validate board settings post boot.

        :raises NotImplementedError: device does not have a finalize stage
        """
        raise NotImplementedError

    @property
    def aftr_iface(self) -> str:
        """AFTR interface name.

        :raises NotImplementedError: device does not have an AFTR IFACE
        """
        raise NotImplementedError

    def get_interface_mtu_size(self, interface: str) -> int:
        """Get the MTU size of the interface in bytes.

        :param interface: name of the interface
        :type interface: str
        :return: size of the MTU in bytes
        :rtype: int
        :raises ValueError: when ifconfig data is not available
        """
        if ifconfig_data := jc.parse(
            "ifconfig",
            self._console.execute_command(f"ifconfig {interface}"),
        ):
            return ifconfig_data[0]["mtu"]  # type: ignore[index]
        msg = f"ifconfig {interface} is not available"
        raise ValueError(msg)


class RPiPrplOSCPE(CPE, BoardfarmDevice):
    """RPi prplOS device class."""

    def __init__(self, config: dict[str, Any], cmdline_args: Namespace) -> None:
        """Initialize RPi prplOS CPE.

        :param config: configuration from inventory
        :type config: Dict
        :param cmdline_args: command line args
        :type cmdline_args: Namespace
        """
        super().__init__(config, cmdline_args)

        self._hw: RPiPrplOSHW = RPiPrplOSHW(config, cmdline_args)
        self._sw: RPiPrplOSSW = None

    @property
    def config(self) -> dict:
        """Get device configuration.

        :returns: device configuration
        """
        return self._config

    @property
    def hw(self) -> RPiPrplOSHW:
        """The Hardware class object.

        :return: object holding hardware component details.
        :rtype: RPiPrplOSHW
        """
        return self._hw

    @property
    def sw(self) -> RPiPrplOSSW:
        """The Software class object.

        :return: object holding software component details.
        :rtype: RPiPrplOSSW
        """
        return self._sw

    @hookimpl
    def boardfarm_device_boot(self, device_manager: DeviceManager) -> None:
        """Boardfarm hook implementation to boot the device.

        This method performs the full boot sequence:
        1. Connect to device consoles
        2. Provision CPE (if provisioner available)
        3. Power cycle the device
        4. Wait for hardware boot (WAN interface up)
        5. Wait for device online (network + TR-181 ready)
        6. Configure TR-069 ACS connection
        7. Wait for ACS connection to be established

        :param device_manager: device manager
        :type device_manager: DeviceManager
        """
        self.hw.connect_to_consoles(self.device_name)
        self._sw = RPiPrplOSSW(self._hw)
        _LOGGER.info("Booting %s(%s) device", self.device_name, self.device_type)
        
        # Provision CPE if provisioner is available
        try:
            if provisioner := device_manager.get_device_by_type(
                Provisioner,  # type: ignore[type-abstract]
            ):
                provisioner.provision_cpe(
                    cpe_mac=self.hw.mac_address, dhcpv4_options={}, dhcpv6_options={}
                )
        except DeviceNotFound:
            _LOGGER.warning(
                "Skipping CPE provisioning. Provisioner for %s(%s) not found!",
                self.device_name,
                self.device_type,
            )
        
        self._sw = RPiPrplOSSW(self._hw)
        self.hw.power_cycle()
        self.hw.wait_for_hw_boot()
        self.sw.wait_device_online()

        # Configure TR-069 and wait for ACS connection
        acs = None
        try:
            acs = device_manager.get_device_by_type(
                ACS,  # type: ignore[type-abstract]
            )
        except DeviceNotFound:
            _LOGGER.warning("ACS device not found, skipping TR-069 configuration")
        
        if acs:
            acs_url = acs.config.get(  # type: ignore[attr-defined]
                "acs_mib",
                "http://acs_server.boardfarm.com:7547",
            )
            _LOGGER.info("Configuring TR-069 ACS URL: %s", acs_url)
            self.sw.configure_management_server(url=acs_url)
            
            _LOGGER.info("TR-069 CPE ID: %s", self.sw.cpe_id)
            
            # Wait for CPE to connect to ACS
            _LOGGER.info("Waiting for CPE to connect to ACS...")
            self.sw.wait_for_acs_connection(acs, timeout=180)
            _LOGGER.info("CPE successfully connected to ACS")
        else:
            _LOGGER.info("TR-069 CPE ID: %s", self.sw.cpe_id)

    def _is_http_gui_running(self) -> bool:
        """Check if uhttpd (LuCI web server) is running and listening on port 80.
        
        uhttpd may listen on 0.0.0.0:80 (all interfaces) or specific IPs.
        """
        # Check if uhttpd is listening on port 80 (any interface)
        output = self.hw.get_console("console").execute_command(
            "netstat -nlp 2>/dev/null | grep ':80 ' | grep -E 'uhttpd|LISTEN'",
        )
        return bool(output and "80" in output)

    @hookimpl
    def boardfarm_device_configure(self) -> None:
        """Configure boardfarm device.

        Ensures the HTTP server (uhttpd for LuCI) is running.
        :raises ConfigurationFailure: if the http service cannot be started
        """
        if retry(self._is_http_gui_running, 5):
            _LOGGER.info("LuCI web interface is running")
            return
        
        # prplOS/OpenWrt uses uhttpd for LuCI web interface
        console = self.hw.get_console("console")
        
        # Check if uhttpd is installed
        uhttpd_check = console.execute_command(
            "test -f /etc/init.d/uhttpd && echo 'installed' || echo 'missing'",
        )
        if "missing" in uhttpd_check:
            _LOGGER.warning(
                "uhttpd not installed on this device. LuCI GUI may not be available."
            )
            return
        
        _LOGGER.info("Starting uhttpd for LuCI web interface...")
        console.execute_command("/etc/init.d/uhttpd restart")
        sleep(3)
        
        # Debug: show what's listening on port 80
        debug_output = console.execute_command("netstat -nlp 2>/dev/null | grep ':80 '")
        _LOGGER.debug("Port 80 listeners: %s", debug_output)
        
        if retry(self._is_http_gui_running, 5):
            _LOGGER.info("LuCI web interface started successfully")
            return
        
        # Not a fatal error - some prplOS builds may not have LuCI
        _LOGGER.warning(
            "LuCI web interface (uhttpd) not responding on port 80. "
            "GUI functionality may not be available."
        )

    @hookimpl
    def boardfarm_shutdown_device(self) -> None:
        """Boardfarm hook implementation to shutdown the device."""
        _LOGGER.info("Shutdown %s(%s) device", self.device_name, self.device_type)
        self.hw.disconnect_from_consoles()

    @hookimpl(tryfirst=True)
    def boardfarm_skip_boot(self) -> None:
        """Boardfarm skip boot hook implementation."""
        _LOGGER.info(
            "Initializing %s(%s) device with skip-boot option",
            self.device_name,
            self.device_type,
        )
        self._hw.connect_to_consoles(self.device_name)
        self._sw = RPiPrplOSSW(self._hw)

    def get_interactive_consoles(self) -> dict[str, BoardfarmPexpect]:
        """Get interactive consoles of the device.

        :return: device interactive consoles
        :rtype: dict[str, BoardfarmPexpect]
        """
        return self.hw.get_interactive_consoles()
