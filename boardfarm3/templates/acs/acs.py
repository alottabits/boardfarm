"""Boardfarm ACS device template."""

from __future__ import annotations

from abc import ABC, abstractmethod
from functools import cached_property
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from boardfarm3.lib.boardfarm_pexpect import BoardfarmPexpect
    from boardfarm3.lib.networking import IptablesFirewall
    from boardfarm3.templates.acs.acs_gui import ACSGUI
    from boardfarm3.templates.acs.acs_nbi import ACSNBI


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
