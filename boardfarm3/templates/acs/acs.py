"""Boardfarm ACS device template."""

from __future__ import annotations

import warnings
from abc import ABC, abstractmethod
from copy import deepcopy
from functools import cached_property
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from boardfarm3.lib.boardfarm_pexpect import BoardfarmPexpect
    from boardfarm3.lib.networking import IptablesFirewall
    from boardfarm3.templates.acs.acs_gui import ACSGUI
    from boardfarm3.templates.acs.acs_nbi import (
        ACSNBI,
        GpvInput,
        GpvResponse,
        SpvInput,
    )


class ACS(ABC):
    """Boardfarm ACS device template."""

    @property
    @abstractmethod
    def config(self) -> dict:
        """Device configuration."""
        raise NotImplementedError

    @property
    @abstractmethod
    def nbi(self) -> ACSNBI:
        """ACS North Bound Interface."""
        raise NotImplementedError

    @property
    @abstractmethod
    def gui(self) -> ACSGUI:
        """ACS GUI."""
        raise NotImplementedError

    @property
    @abstractmethod
    def console(self) -> BoardfarmPexpect:
        """Returns ACS console.

        :return: console
        :rtype: BoardfarmPexpect
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def url(self) -> str:
        """Returns the acs url used.

        :return: acs url component instance
        :rtype: str
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def firewall(self) -> IptablesFirewall:
        """Returns Firewall iptables instance.

        :return: firewall iptables instance with console object
        :rtype: IptablesFirewall
        """
        raise NotImplementedError

    @cached_property
    @abstractmethod
    def ipv4_addr(self) -> str:
        """Return the IPv4 address on IFACE facing DUT.

        :return: IPv4 address in string format.
        :rtype: str
        """
        raise NotImplementedError

    @cached_property
    @abstractmethod
    def ipv6_addr(self) -> str:
        """Return the IPv6 address on IFACE facing DUT.

        :return: IPv6 address in string format.
        :rtype: str
        """
        raise NotImplementedError

    @abstractmethod
    def start_tcpdump(
        self,
        interface: str,
        port: str | None,
        output_file: str = "pkt_capture.pcap",
        filters: dict | None = None,
        additional_filters: str | None = "",
    ) -> str:
        """Start tcpdump capture on given interface.

        :param interface: inteface name where packets to be captured
        :type interface: str
        :param port: port number, can be a range of ports(eg: 443 or 433-443)
        :type port: str
        :param output_file: pcap file name, Defaults: pkt_capture.pcap
        :type output_file: str
        :param filters: filters as key value pair(eg: {"-v": "", "-c": "4"})
        :type filters: Optional[Dict]
        :param additional_filters: additional filters
        :type additional_filters: Optional[str]
        :raises ValueError: on failed to start tcpdump
        :return: console ouput and tcpdump process id
        :rtype: str
        """
        raise NotImplementedError

    @abstractmethod
    def stop_tcpdump(self, process_id: str) -> None:
        """Stop tcpdump capture.

        :param process_id: tcpdump process id
        :type process_id: str
        """
        raise NotImplementedError

    # =========================================================================
    # Compatibility Shims (Deprecated)
    # =========================================================================

    def _warn_deprecation(self, method_name: str) -> None:
        warnings.warn(
            f"Accessing '{method_name}' directly on the ACS device is deprecated. "
            f"Please use 'acs.nbi.{method_name}' instead.",
            DeprecationWarning,
            stacklevel=2,
        )

    def GPV(
        self,
        param: GpvInput,
        timeout: int | None = None,
        cpe_id: str | None = None,
    ) -> GpvResponse:
        """Send GetParamaterValues command via ACS server (Deprecated)."""
        self._warn_deprecation("GPV")
        return self.nbi.GPV(param, timeout, cpe_id)

    def SPV(
        self,
        param_value: SpvInput,
        timeout: int | None = None,
        cpe_id: str | None = None,
    ) -> int:
        """Send SetParamaterValues command via ACS server (Deprecated)."""
        self._warn_deprecation("SPV")
        return self.nbi.SPV(param_value, timeout, cpe_id)

    def GPA(
        self,
        param: str,
        cpe_id: str | None = None,
    ) -> list[dict]:
        """Get parameter attribute of the parameter specified (Deprecated)."""
        self._warn_deprecation("GPA")
        return self.nbi.GPA(param, cpe_id)

    def SPA(
        self,
        param: list[dict] | dict,
        notification_param: bool = True,
        access_param: bool = False,
        access_list: list | None = None,
        cpe_id: str | None = None,
    ) -> list[dict]:
        """Set parameter attribute of the parameter specified (Deprecated)."""
        self._warn_deprecation("SPA")
        return self.nbi.SPA(
            param, notification_param, access_param, access_list, cpe_id
        )

    def FactoryReset(self, cpe_id: str | None = None) -> list[dict]:
        """Execute FactoryReset RPC (Deprecated)."""
        self._warn_deprecation("FactoryReset")
        return self.nbi.FactoryReset(cpe_id)

    def Reboot(
        self,
        CommandKey: str = "reboot",
        cpe_id: str | None = None,
    ) -> list[dict]:
        """Execute Reboot (Deprecated)."""
        self._warn_deprecation("Reboot")
        return self.nbi.Reboot(CommandKey, cpe_id)

    def AddObject(
        self,
        param: str,
        param_key: str = "",
        cpe_id: str | None = None,
    ) -> list[dict]:
        """Add object ACS (Deprecated)."""
        self._warn_deprecation("AddObject")
        return self.nbi.AddObject(param, param_key, cpe_id)

    def DelObject(
        self,
        param: str,
        param_key: str = "",
        cpe_id: str | None = None,
    ) -> list[dict]:
        """Delete object ACS (Deprecated)."""
        self._warn_deprecation("DelObject")
        return self.nbi.DelObject(param, param_key, cpe_id)

    def GPN(
        self,
        param: str,
        next_level: bool,
        timeout: int | None = None,
        cpe_id: str | None = None,
    ) -> list[dict]:
        """Discover the Parameters (Deprecated)."""
        self._warn_deprecation("GPN")
        return self.nbi.GPN(param, next_level, timeout, cpe_id)

    def ScheduleInform(
        self,
        CommandKey: str = "Test",
        DelaySeconds: int = 20,
        cpe_id: str | None = None,
    ) -> list[dict]:
        """Execute ScheduleInform RPC (Deprecated)."""
        self._warn_deprecation("ScheduleInform")
        return self.nbi.ScheduleInform(CommandKey, DelaySeconds, cpe_id)

    def GetRPCMethods(self, cpe_id: str | None = None) -> list[dict]:
        """Execute GetRPCMethods RPC (Deprecated)."""
        self._warn_deprecation("GetRPCMethods")
        return self.nbi.GetRPCMethods(cpe_id)

    def Download(
        self,
        url: str,
        filetype: str = "1 Firmware Upgrade Image",
        targetfilename: str = "",
        filesize: int = 200,
        username: str = "",
        password: str = "",
        commandkey: str = "",
        delayseconds: int = 10,
        successurl: str = "",
        failureurl: str = "",
        cpe_id: str | None = None,
    ) -> list[dict]:
        """Execute Download RPC (Deprecated)."""
        self._warn_deprecation("Download")
        return self.nbi.Download(
            url,
            filetype,
            targetfilename,
            filesize,
            username,
            password,
            commandkey,
            delayseconds,
            successurl,
            failureurl,
            cpe_id,
        )

    def provision_cpe_via_tr069(
        self,
        tr069provision_api_list: list[dict[str, list[dict[str, str]]]],
        cpe_id: str,
    ) -> None:
        """Provision the cable modem via TR069 (Deprecated)."""
        self._warn_deprecation("provision_cpe_via_tr069")
        return self.nbi.provision_cpe_via_tr069(tr069provision_api_list, cpe_id)

    def delete_file(self, filename: str) -> None:
        """Delete file (Deprecated).

        NOTE: This delegates to NBI which delegates back to device (if console exists).
        If strict compliance is needed, we should check if NBI implements it.
        But ACSNBI template has it.
        """
        self._warn_deprecation("delete_file")
        return self.nbi.delete_file(filename)

    def scp_device_file_to_local(self, local_path: str, source_path: str) -> None:
        """SCP file (Deprecated)."""
        self._warn_deprecation("scp_device_file_to_local")
        return self.nbi.scp_device_file_to_local(local_path, source_path)
