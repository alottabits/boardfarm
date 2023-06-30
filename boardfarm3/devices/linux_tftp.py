"""Boardfarm Linux TFTP device module."""

import logging
from ipaddress import IPv4Address

from boardfarm3 import hookimpl
from boardfarm3.devices.base_devices import LinuxDevice
from boardfarm3.exceptions import ConfigurationFailure, DeviceBootFailure
from boardfarm3.lib.device_manager import DeviceManager
from boardfarm3.templates.tftp import TFTP

_LOGGER = logging.getLogger(__name__)


class LinuxTFTP(LinuxDevice, TFTP):
    """Boardfarm Linux LAN side TFTP device.

    This is a disposable device that can be used when a LAN side tftp server
    is needed. I.e. for some CPEs flashing via bootloader requires a LAN side
    tftp device. This device is disconnected on post deploy.
    """

    _tftpboot_dir = "/tftpboot"
    _internet_access_cmd = "mgmt"
    # This value will be updated on every LinuxTFTP device boot
    # to make sure every LinuxTFTP device has a unique static ip address
    _last_static_ip_address = IPv4Address("192.168.1.10")

    @hookimpl
    def boardfarm_server_boot(self) -> None:
        """Boardfarm hook implementation to boot TFTP device.

        :raises DeviceBootFailure: if tftpd fails to start
        """
        _LOGGER.info("Booting %s(%s) device", self.device_name, self.device_type)
        self._connect()
        if self._cmdline_args.skip_boot:
            return
        # TODO: to be cleaned up once Docker factory comes into place
        self._set_eth_interface_ipv4_address(LinuxTFTP._last_static_ip_address)
        LinuxTFTP._last_static_ip_address += 1
        if "Restarting" not in self._console.execute_command(
            "/etc/init.d/tftpd-hpa restart",
        ):
            msg = "Failed to restart tftpd-hpa"
            raise DeviceBootFailure(msg)
        if "in.tftpd is running" not in self._console.execute_command(
            "/etc/init.d/tftpd-hpa status",
        ):
            msg = "Failed tftpd-hpa not running"
            raise DeviceBootFailure(msg)

    @hookimpl
    def boardfarm_post_deploy_devices(self, device_manager: DeviceManager) -> None:
        """Boardfarm hook implementation to shutdown TFTP device.

        :param device_manager: device manager instance
        :type device_manager: DeviceManager
        """
        _LOGGER.info("Shutdown %s(%s) device", self.device_name, self.device_type)
        self._console.execute_command("/etc/init.d/tftpd-hpa stop")
        self._disconnect()
        device_manager.unregister_device(self.device_name)

    def download_image_from_uri(self, image_uri: str) -> str:
        """Download image from given URI.

        :param image_uri: image file URI
        :type image_uri: str
        :returns: downloaded image name
        :rtype: str
        """
        return self.download_file_from_uri(image_uri, self._tftpboot_dir)

    def _set_eth_interface_ipv4_address(self, static_ip: IPv4Address) -> None:
        """Set a static IPv4 on the DUT connected interface.

        :param static_ip: static ipv4 address
        :type static_ip: IPv4Address
        :raises ConfigurationFailure: On failed to set given static ip
        """
        self._console.execute_command(
            f"ifconfig {self.eth_interface} {static_ip} netmask 255.255.255.0 up",
        )
        if str(static_ip) != self._get_nw_interface_ipv4_address(self.eth_interface):
            msg = f"Failed to configure {self.eth_interface} with {static_ip}"
            raise ConfigurationFailure(
                msg,
            )