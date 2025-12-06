"""ACS GUI Template.

This template defines task-oriented GUI operations for ACS systems.
Following the same pattern as ACSNBI, methods describe WHAT to do,
not HOW to navigate the UI.

Implementations use semantic element search for resilience to UI changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from boardfarm3.templates.acs.acs import ACS


class ACSGUI(ABC):
    """ACS GUI Template.
    
    Task-oriented interface for ACS GUI operations. Methods are vendor-neutral
    and describe business operations rather than UI navigation.
    
    Device-specific implementations should use semantic element search
    (find_element_by_function) to make tests resilient to UI changes.
    """

    def __init__(self, device: ACS) -> None:
        """Initialize ACS GUI.
        
        :param device: Parent ACS device
        :type device: ACS
        """
        self.device = device
    
    @property
    def config(self) -> dict:
        """Device config."""
        return self.device.config

    # ========================================================================
    # Authentication Methods
    # ========================================================================

    @abstractmethod
    def login(self, username: str | None = None, password: str | None = None) -> bool:
        """Login to the ACS GUI.
        
        :param username: Username for login (uses config if None)
        :type username: Optional[str]
        :param password: Password for login (uses config if None)
        :type password: Optional[str]
        :return: True if login successful
        :rtype: bool
        :raises: Exception if login fails
        """
        raise NotImplementedError

    @abstractmethod
    def logout(self) -> bool:
        """Logout from the ACS GUI.
        
        :return: True if logout successful
        :rtype: bool
        """
        raise NotImplementedError

    @abstractmethod
    def is_logged_in(self) -> bool:
        """Check if currently logged into the GUI.
        
        :return: True if logged in
        :rtype: bool
        """
        raise NotImplementedError

    # ========================================================================
    # Device Discovery & Navigation Methods
    # ========================================================================

    @abstractmethod
    def search_device(self, cpe_id: str) -> bool:
        """Search for a device by CPE ID.
        
        This method searches for a device but doesn't necessarily navigate
        to its details page. Use get_device_status() or similar for operations.
        
        :param cpe_id: CPE identifier
        :type cpe_id: str
        :return: True if device found
        :rtype: bool
        """
        raise NotImplementedError

    @abstractmethod
    def get_device_count(self) -> int:
        """Get total number of devices managed by ACS.
        
        :return: Number of devices
        :rtype: int
        """
        raise NotImplementedError

    @abstractmethod
    def filter_devices(self, filter_criteria: dict[str, str]) -> int:
        """Apply filter criteria to device list.
        
        :param filter_criteria: Dictionary of field:value filters
        :type filter_criteria: dict[str, str]
        :return: Number of devices matching filter
        :rtype: int
        
        Example:
            >>> gui.filter_devices({"status": "online", "model": "XB8"})
        """
        raise NotImplementedError

    # ========================================================================
    # Device Status & Information Methods
    # ========================================================================

    @abstractmethod
    def get_device_status(self, cpe_id: str) -> dict[str, str]:
        """Get device status information via GUI.
        
        :param cpe_id: CPE identifier
        :type cpe_id: str
        :return: Dictionary with status information (online, last_inform, etc.)
        :rtype: dict[str, str]
        
        Example return:
            {
                "status": "online",
                "last_inform": "2024-12-06T20:30:00Z",
                "ip_address": "192.168.1.1",
                "software_version": "1.2.3"
            }
        """
        raise NotImplementedError

    @abstractmethod
    def verify_device_online(self, cpe_id: str, timeout: int = 60) -> bool:
        """Verify device is online within timeout period.
        
        :param cpe_id: CPE identifier
        :type cpe_id: str
        :param timeout: Maximum wait time in seconds
        :type timeout: int
        :return: True if device comes online within timeout
        :rtype: bool
        """
        raise NotImplementedError

    @abstractmethod
    def get_last_inform_time(self, cpe_id: str) -> str:
        """Get the timestamp of device's last inform.
        
        :param cpe_id: CPE identifier
        :type cpe_id: str
        :return: Last inform timestamp (ISO format)
        :rtype: str
        """
        raise NotImplementedError

    # ========================================================================
    # Device Operation Methods
    # ========================================================================

    @abstractmethod
    def reboot_device_via_gui(self, cpe_id: str) -> bool:
        """Reboot a device via the GUI.
        
        Note: This only initiates the reboot. Test should wait for device
        to come back online using verify_device_online().
        
        :param cpe_id: CPE identifier
        :type cpe_id: str
        :return: True if reboot initiated successfully
        :rtype: bool
        :raises: Exception if reboot fails to initiate
        """
        raise NotImplementedError

    @abstractmethod
    def factory_reset_via_gui(self, cpe_id: str) -> bool:
        """Factory reset a device via the GUI.
        
        Note: This only initiates the factory reset. Test should handle
        waiting and verification.
        
        :param cpe_id: CPE identifier
        :type cpe_id: str
        :return: True if factory reset initiated successfully
        :rtype: bool
        :raises: Exception if factory reset fails to initiate
        """
        raise NotImplementedError

    @abstractmethod
    def delete_device_via_gui(self, cpe_id: str, confirm: bool = True) -> bool:
        """Delete a device from ACS via GUI.
        
        :param cpe_id: CPE identifier
        :type cpe_id: str
        :param confirm: Whether to confirm the deletion
        :type confirm: bool
        :return: True if deletion successful
        :rtype: bool
        """
        raise NotImplementedError

    # ========================================================================
    # Parameter Operation Methods
    # ========================================================================

    @abstractmethod
    def get_device_parameter_via_gui(
        self, 
        cpe_id: str, 
        parameter: str
    ) -> str | None:
        """Get a device parameter value via GUI.
        
        :param cpe_id: CPE identifier
        :type cpe_id: str
        :param parameter: TR-069 parameter path
        :type parameter: str
        :return: Parameter value or None if not found
        :rtype: Optional[str]
        
        Example:
            >>> value = gui.get_device_parameter_via_gui(
            ...     cpe_id="ABC123",
            ...     parameter="Device.WiFi.SSID.1.SSID"
            ... )
        """
        raise NotImplementedError

    @abstractmethod
    def set_device_parameter_via_gui(
        self,
        cpe_id: str,
        parameter: str,
        value: str,
    ) -> bool:
        """Set a device parameter value via GUI.
        
        :param cpe_id: CPE identifier
        :type cpe_id: str
        :param parameter: TR-069 parameter path
        :type parameter: str
        :param value: Value to set
        :type value: str
        :return: True if parameter set successfully
        :rtype: bool
        
        Example:
            >>> gui.set_device_parameter_via_gui(
            ...     cpe_id="ABC123",
            ...     parameter="Device.WiFi.SSID.1.SSID",
            ...     value="MyNetwork"
            ... )
        """
        raise NotImplementedError

    # ========================================================================
    # Firmware Operation Methods
    # ========================================================================

    @abstractmethod
    def trigger_firmware_upgrade_via_gui(
        self,
        cpe_id: str,
        firmware_url: str,
    ) -> bool:
        """Trigger firmware upgrade for a device via GUI.
        
        Note: This only initiates the upgrade. Test should handle waiting
        and verification of upgrade completion.
        
        :param cpe_id: CPE identifier
        :type cpe_id: str
        :param firmware_url: URL of firmware image
        :type firmware_url: str
        :return: True if upgrade initiated successfully
        :rtype: bool
        """
        raise NotImplementedError

    @abstractmethod
    def verify_firmware_version_via_gui(
        self,
        cpe_id: str,
        expected_version: str,
    ) -> bool:
        """Verify device firmware version via GUI.
        
        :param cpe_id: CPE identifier
        :type cpe_id: str
        :param expected_version: Expected firmware version
        :type expected_version: str
        :return: True if version matches expected
        :rtype: bool
        """
        raise NotImplementedError
