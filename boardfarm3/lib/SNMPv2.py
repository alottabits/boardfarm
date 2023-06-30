"""SNMP v2 module for SNMP communication."""  # pylint: disable=invalid-name


import re
from typing import Optional

from boardfarm3.exceptions import SNMPError
from boardfarm3.lib.mibs_compiler import MibsCompiler
from boardfarm3.templates.wan import WAN


class SNMPv2:
    """SNMP v2 module for SNMP communication."""

    def __init__(
        self,
        device: WAN,
        target_ip: str,
        mibs_compiler: MibsCompiler,
    ) -> None:
        """Initialize SNMPv2.

        :param device: device instance
        :type device: WAN
        :param target_ip: target ip address
        :type target_ip: str
        :param mibs_compiler: mibs compiler instance
        :type mibs_compiler: MibsCompiler
        """
        self._device = device
        self._target_ip = target_ip
        self._mibs_compiler = mibs_compiler

    def _get_mib_oid(self, mib_name: str) -> str:
        oid_regex = r"^([1-9][0-9]{0,6}|0)(\.([1-9][0-9]{0,6}|0)){3,30}$"
        if re.match(oid_regex, mib_name):
            oid = mib_name
        else:
            try:
                oid = self._mibs_compiler.get_mib_oid(mib_name)
            except ValueError as exception:
                msg = f"MIB not available, Error: {exception}"
                raise SNMPError(msg) from exception
        return oid

    def snmpget(  # noqa: PLR0913
        self,
        mib_name: str,
        index: int = 0,
        community: str = "private",
        extra_args: str = "",
        timeout: int = 10,
        retries: int = 3,
    ) -> tuple[str, str, str]:
        """Perform an snmpget with given arguments.

        :param mib_name: mib name used to perform snmp
        :type mib_name: str
        :param index: index used along with mib_name
        :type index: int
        :param community: SNMP Community string that allows access to DUT,
                            defaults to 'private'
        :type community: str
        :param extra_args: Any extra arguments to be passed in the command
        :type extra_args: str
        :param timeout: timeout in seconds
        :type timeout: int
        :param retries: the no. of time the commands are executed on exception/timeout
        :type retries: int
        :return: value, value type and complete output
        :rtype: Tuple[str, str, str]
        """
        oid = self._get_mib_oid(mib_name) + f".{index!s}"
        output = self._run_snmp_command(
            "snmpget",
            community,
            oid,
            timeout,
            retries,
            extra_args=extra_args,
        )
        return self._parse_snmp_output(oid, output)

    def snmpset(  # pylint: disable=too-many-arguments  # noqa: PLR0913
        self,
        mib_name: str,
        value: str,
        stype: str,
        index: int = 0,
        community: str = "private",
        extra_args: str = "",
        timeout: int = 10,
        retries: int = 3,
    ) -> tuple[str, str, str]:
        """Perform an snmpset with given arguments.

        :param mib_name: mib name used to perform snmp
        :type mib_name: str
        :param value: value to be set for the mib name
        :type value: str
        :param stype: defines the datatype of value to be set for mib_name
                        stype: one of i, u, t, a, o, s, x, d, b
                        i: INTEGER, u: unsigned INTEGER, t: TIMETICKS, a: IPADDRESS
                        o: OBJID, s: STRING, x: HEX STRING, d: DECIMAL STRING, b: BITS
                        U: unsigned int64, I: signed int64, F: float, D: double
        :type stype: str
        :param index: index used along with mib_name
        :type index: int
        :param community: SNMP Community string that allows access to DUT,
                        defaults to 'private'
        :type community: str
        :param extra_args: Any extra arguments to be passed in the command
        :type extra_args: str
        :param timeout: timeout in seconds
        :type timeout: int
        :param retries: the no. of time the commands are executed on exception/timeout
        :type retries: int
        :return: value, value type and complete output
        :rtype: Tuple[str, str, str]
        """
        oid = self._get_mib_oid(mib_name) + f".{index!s}"
        if re.findall(r"\s", value.strip()) and stype == "s":
            value = f"{value!r}"
        if str(value).lower().startswith("0x"):
            set_value = f"{stype} '{value[2:].upper()}'"
        else:
            set_value = f"{stype} '{value}'"
        output = self._run_snmp_command(
            "snmpset",
            community,
            oid,
            timeout,
            retries,
            set_value=set_value,
            extra_args=extra_args,
        )
        return self._parse_snmp_output(oid, output, value)

    def _run_snmp_command(  # pylint: disable=too-many-arguments  # noqa: PLR0913
        self,
        action: str,
        community: str,
        oid: str,
        timeout: int,
        retries: int,
        set_value: str = "",
        extra_args: str = "",
    ) -> str:
        cmd = self._create_snmp_cmd(
            action,
            community,
            timeout,
            retries,
            oid,
            set_value,
            extra_args,
        )
        return self._device.execute_snmp_command(cmd)

    def _create_snmp_cmd(  # pylint: disable=too-many-arguments  # noqa: PLR0913
        self,
        action: str,
        community: str,
        timeout: int,
        retries: int,
        oid: str,
        set_value: str = "",
        extra_args: str = "",
    ) -> str:
        if extra_args:
            extra_args = " " + extra_args.strip()
        return (
            f"{action} -v 2c -On{extra_args} -c {community} -t {timeout} -r"
            f" {retries} {self._target_ip} {oid} {set_value}"
        )

    def _parse_snmp_output(
        self,
        oid: str,
        output: str,
        value: Optional[str] = None,
    ) -> tuple[str, str, str]:
        """Return the tuple with value, type of the value and snmp command output.

        :param oid: object ID
        :param output: SNMP output
        :param value: additional options
        :returns: parsed output
        :raises SNMPError: no matching output
        :raises AssertionError: set value did not match with output value
        """
        result_pattern = rf".{oid}\s+\=\s+(\S+)\:\s+(\"?.*\"?)"
        match = re.search(result_pattern, output)
        if not match:
            raise SNMPError(output)
        if value:
            value = value.strip("'").strip("0x")
            if value not in match[2]:
                err_msg = (
                    "Set value did not match with output value: Expected: "
                    f"{value} Actual: {match[2]}"
                )
                raise AssertionError(err_msg)

        return match[2].replace('"', ""), match[1], match.group()

    def _parse_snmpwalk_output(
        self,
        oid: str,
        output: str,
    ) -> tuple[dict[str, list[str]], str]:
        """Return list of dictionary of mib_oid as key and list(value, type) value.

        :param oid: object ID
        :param output: SNMP output
        :returns: parsed output
        :raises SNMPError: no matching output
        """
        result_pattern = rf".({oid}[\.\d+]*)\s+\=\s+(\S+)\:\s+(\"?.*\"?)"
        walk_key_value_dict: dict[str, list[str]] = {}
        match = re.findall(result_pattern, output)
        if not match:
            raise SNMPError(output)
        for m in match:
            walk_key_value_dict[m[0]] = [m[2].replace('"', ""), m[1]]
        return walk_key_value_dict, output

    def snmpwalk(  # noqa: PLR0913
        self,
        mib_name: str,
        index: int = None,
        community: str = "private",
        retries: int = 3,
        timeout: int = 100,
        extra_args: str = "",
    ) -> tuple[dict[str, list[str]], str]:
        """Perform an snmpwalk with given arguments.

        :param mib_name: mib name used to perform snmp
        :type mib_name: str
        :param index: index used along with mib_name
        :type index: int
        :param community: SNMP Community string that allows access to DUT,
                            defaults to 'private'
        :type community: str
        :param retries: the no. of time the commands are executed on exception/timeout
        :type retries: int
        :param timeout: timeout in seconds
        :type timeout: int
        :param extra_args: Any extra arguments to be passed in the command
        :type extra_args: str
        :return: dictionary of mib_oid as key and list(value, type) as value
                            and complete output
        :rtype: Tuple[Dict[str, List[str]], str]
        :raises SNMPError: no matching output
        """
        if mib_name:
            try:
                oid = self._get_mib_oid(mib_name)
                if index:
                    oid = oid + f".{index!s}"
            except (ValueError, SNMPError) as exception:
                msg = f"MIB not available, Error: {exception}"
                raise SNMPError(msg) from exception
        else:
            oid = ""
        output = self._run_snmp_command(
            "snmpwalk",
            community,
            oid,
            timeout,
            retries,
            extra_args=extra_args,
        )
        return self._parse_snmpwalk_output(oid, output)