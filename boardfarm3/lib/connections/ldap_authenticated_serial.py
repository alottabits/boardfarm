"""SSH connection module."""


from typing import Any

import pexpect

from boardfarm3.exceptions import DeviceConnectionError
from boardfarm3.lib.connections.ssh_connection import SSHConnection


class LdapAuthenticatedSerial(SSHConnection):
    """Connect to a serial with ldap credentials."""

    def __init__(  # noqa: PLR0913
        self,
        name: str,
        ip_addr: str,
        ldap_credentials: str,
        shell_prompt: list[str],
        port: int = 22,
        save_console_logs: bool = False,
        **kwargs: dict[str, Any],  # ignore other arguments  # noqa: ARG002
    ) -> None:
        """Initialize ldap authenticated serial connection.

        :param name: connection name
        :type name: str
        :param ip_addr: server ip address
        :type ip_addr: str
        :param ldap_credentials: ldap credentials
        :type ldap_credentials: str
        :param shell_prompt: shell prompt patterns
        :type shell_prompt: list[str]
        :param port: port number, defaults to 22
        :type port: int
        :param save_console_logs: save console logs to disk, defaults to False
        :type save_console_logs: bool
        :param kwargs: other keyword arguments
        :raises ValueError: invalid LDAP credentials
        """
        if ";" not in ldap_credentials:
            msg = "Invalid LDAP credentials"
            raise ValueError(msg)
        username, password = ldap_credentials.split(";")
        super().__init__(
            name,
            ip_addr,
            username,
            shell_prompt,
            port,
            password,
            save_console_logs,
        )

    def _login_to_server(self, password: str) -> None:
        """Login to serial server.

        :param password: LDAP password
        :type password: str
        :raises DeviceConnectionError: failed to connect to device via serial
        """
        if self.expect(["Password:", pexpect.EOF, pexpect.TIMEOUT]):
            msg = "Failed to connect to device via serial"
            raise DeviceConnectionError(msg)
        self.sendline(password)
        if self.expect_exact(["OpenGear Serial Server", pexpect.EOF, pexpect.TIMEOUT]):
            msg = "Failed to connect to device via serial"
            raise DeviceConnectionError(msg)