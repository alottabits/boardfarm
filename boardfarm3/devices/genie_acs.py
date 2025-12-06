"""GenieACS module."""

from __future__ import annotations

import logging
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from time import time as time_now
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urljoin

import httpx
from typing_extensions import LiteralString

from boardfarm3 import hookimpl
from boardfarm3.devices.base_devices import LinuxDevice
from boardfarm3.exceptions import (
    BoardfarmException,
    ContingencyCheckError,
    NotSupportedError,
)
from boardfarm3.lib.utils import retry_on_exception
from boardfarm3.templates.acs import (
    ACS,
    ACSGUI,
    ACSNBI,
    GpvInput,
    GpvResponse,
    SpvInput,
)
from boardfarm3.templates.cpe.cpe import CPE

if TYPE_CHECKING:
    from boardfarm3.lib.boardfarm_pexpect import BoardfarmPexpect
    from boardfarm3.lib.device_manager import DeviceManager
    from boardfarm3.lib.networking import IptablesFirewall

_DEFAULT_TIMEOUT = 60 * 2
_LOGGER = logging.getLogger(__name__)


# pylint: disable=too-many-public-methods
class GenieAcsNBI(ACSNBI):
    """GenieACS NBI Implementation."""

    CPE_wait_time = _DEFAULT_TIMEOUT

    def __init__(self, device: GenieACS) -> None:
        """Initialize GenieACS NBI.

        :param device: Parent GenieACS device
        """
        super().__init__(device)
        self._client: httpx.Client | None = None
        self._cpeid: str | None = None
        self._base_url: str | None = None

    def initialize(self) -> None:
        """Initialize NBI client connection."""
        self._disable_log_messages_from_libraries()
        self._init_nbi_client()

    def close(self) -> None:
        """Close NBI client connection."""
        if self._client:
            self._client.close()

    def _disable_log_messages_from_libraries(self) -> None:
        """Disable logs from httpx."""
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)

    def _init_nbi_client(self) -> None:
        if self._client is None:
            config = self.device.config
            self._base_url = (
                f"http://{config.get('ipaddr')}:{config.get('http_port')}"
            )
            self._client = httpx.Client(
                auth=(
                    config.get("http_username", "admin"),
                    config.get("http_password", "admin"),
                ),
            )
            try:
                # do a request to test the connection
                self._request_get("/files")
            except (httpx.ConnectError, httpx.HTTPError) as exc:
                raise ConnectionError from exc

    def _request_get(
        self,
        endpoint: str,
        timeout: int | None = CPE_wait_time,
    ) -> Any:  # noqa: ANN401
        request_url = urljoin(self._base_url, endpoint)
        try:
            response = self._client.get(request_url, timeout=timeout)
            response.raise_for_status()
        except (httpx.ConnectError, httpx.HTTPError) as exc:
            raise ConnectionError from exc
        return response.json()

    def _request_post(
        self,
        endpoint: str,
        data: dict[str, Any] | list[Any],
        conn_request: bool = True,
        timeout: int | None = None,
    ) -> Any:  # noqa: ANN401
        if conn_request:
            # GenieACS requires '?connection_request=' (with equals) to trigger immediate connection
            request_url = urljoin(self._base_url, f"{endpoint}?connection_request=")
        else:
            err_msg = (
                "It is unclear how the code would work without 'conn_request' "
                "being True. /FC"
            )
            raise ValueError(err_msg)
        try:
            timeout = timeout if timeout else self.CPE_wait_time
            response = self._client.post(request_url, json=data, timeout=timeout)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # Capture error details from response body
            error_msg = f"HTTP {exc.response.status_code}"
            try:
                error_body = exc.response.json()
                if isinstance(error_body, dict):
                    error_detail = error_body.get("error") or error_body.get("message") or str(error_body)
                    error_msg = f"{error_msg}: {error_detail}"
                else:
                    error_msg = f"{error_msg}: {error_body}"
            except Exception:  # noqa: BLE001
                error_msg = f"{error_msg}: {exc.response.text[:200]}"
            _LOGGER.error("GenieACS API error: %s", error_msg)
            raise ConnectionError(error_msg) from exc
        except (httpx.ConnectError, httpx.HTTPError) as exc:
            raise ConnectionError from exc
        return response.json()

    def GPA(self, param: str, cpe_id: str | None = None) -> list[dict]:
        """Execute GetParameterAttributes RPC call."""
        raise NotImplementedError

    def SPA(
        self,
        param: list[dict] | dict,
        notification_param: bool = True,
        access_param: bool = False,
        access_list: list | None = None,
        cpe_id: str | None = None,
    ) -> list[dict]:
        """Execute SetParameterAttributes RPC call."""
        raise NotImplementedError

    def _build_input_structs(self, param: str | list[str]) -> str:
        return param if isinstance(param, str) else ",".join(param)

    def _flatten_dict(
        self,
        nested_dictionary: dict,
        parent_key: str = "",
        sep: str = ".",
    ) -> dict[Any, Any]:
        items: list = []
        for key, value in nested_dictionary.items():
            new_key = f"{parent_key}{sep}{key}" if parent_key else key
            if isinstance(value, dict):
                items.extend(self._flatten_dict(value, new_key, sep=sep).items())
            else:
                items.append((new_key, value))
        return dict(items)

    def _convert_to_string(self, data: Any) -> LiteralString:  # noqa: ANN401
        flattened_dict = self._flatten_dict(data)
        result = []
        for key, value in flattened_dict.items():
            if "_value" in key:
                result.append(
                    f"{key.strip('._value')}, {value}, "
                    f"{flattened_dict[key.replace('_value', '_type')]}",
                )
        return ", ".join(result)

    def _convert_response(
        self,
        response_data: Any,  # noqa: ANN401
    ) -> list[dict[str, Any]]:
        elements = self._convert_to_string(response_data[0]).split(", ")
        return [
            dict(zip(("key", "value", "type"), elements[i : i + 3]))
            for i in range(0, len(elements), 3)
        ]

    def GPV(
        self,
        param: GpvInput,
        timeout: int | None = None,
        cpe_id: str | None = None,
    ) -> GpvResponse:
        """Send GetParamaterValues command via ACS server."""
        cpe_id = cpe_id if cpe_id else self._cpeid
        quoted_id = quote('{"_id":"' + cpe_id + '"}', safe="")
        self._request_post(
            endpoint="/devices/" + quote(cpe_id) + "/tasks",
            data=self._build_input_structs_gpv(param),
            conn_request=True,
            timeout=timeout,
        )
        response_data = self._request_get(
            "/devices"  # noqa: ISC003
            + "?query="
            + quoted_id
            + "&projection="
            + self._build_input_structs(param),
            timeout=timeout,
        )
        return GpvResponse(self._convert_response(response_data))

    def _build_input_structs_gpv(self, param_value: str | list[str]) -> dict[str, Any]:
        if isinstance(param_value, list):
            return {"name": "getParameterValues", "parameterNames": param_value}
        return {"name": "getParameterValues", "parameterNames": [param_value]}

    def _build_input_structs_spv(
        self,
        param_value: dict[str, Any] | list[dict[str, Any]],
    ) -> dict[str, Any]:
        data = []
        for spv_params in param_value:
            if isinstance(spv_params, dict):
                for key, value in spv_params.items():
                    data.append([key, value])
            elif isinstance(spv_params, str) and isinstance(param_value, dict):
                data.append([spv_params, param_value[spv_params]])
        return {"name": "setParameterValues", "parameterValues": data}

    def SPV(
        self,
        param_value: SpvInput,
        timeout: int | None = None,
        cpe_id: str | None = None,
    ) -> int:
        """Execute SetParameterValues RPC call."""
        cpe_id = cpe_id if cpe_id else self._cpeid
        spv_data = self._build_input_structs_spv(param_value)
        response_data = self._request_post(
            endpoint="/devices/" + quote(cpe_id) + "/tasks",
            data=spv_data,
            conn_request=True,
            timeout=timeout,
        )
        return 0 if response_data else 1

    def FactoryReset(self, cpe_id: str | None = None) -> list[dict]:
        """Execute FactoryReset RPC."""
        raise NotImplementedError

    def Reboot(
        self,
        CommandKey: str = "reboot",
        cpe_id: str | None = None,
    ) -> list[dict]:
        """Execute Reboot RPC via GenieACS NBI API."""
        if not cpe_id:
            raise ValueError("cpe_id is required for Reboot operation")

        reboot_task = {
            "name": "reboot",
            "commandKey": CommandKey,
        }

        self._request_post(
            endpoint="/devices/" + quote(cpe_id) + "/tasks",
            data=reboot_task,
            conn_request=True,
            timeout=30,
        )

        _LOGGER.info("Reboot task created for CPE %s (CommandKey: %s)", cpe_id, CommandKey)
        return []

    def AddObject(
        self,
        param: str,
        param_key: str = "",
        cpe_id: str | None = None,
    ) -> list[dict]:
        """Execute AddOjbect RPC call."""
        raise NotImplementedError

    def DelObject(
        self,
        param: str,
        param_key: str = "",
        cpe_id: str | None = None,
    ) -> list[dict]:
        """Execute DeleteObject RPC call."""
        raise NotImplementedError

    def GPN(
        self,
        param: str,
        next_level: bool,
        timeout: int | None = None,
        cpe_id: str | None = None,
    ) -> list[dict]:
        """Execute GetParameterNames RPC call."""
        raise NotImplementedError

    def ScheduleInform(
        self,
        CommandKey: str = "Test",  # noqa: ARG002
        DelaySeconds: int = 20,
        cpe_id: str | None = None,
    ) -> list[dict]:
        """Execute ScheduleInform RPC."""
        cpe_id = cpe_id if cpe_id else self._cpeid
        if not cpe_id:
            msg = "cpe_id must be provided or set in device config"
            raise ValueError(msg)

        if DelaySeconds == 0:
            gpv_task = {
                "name": "getParameterValues",
                "parameterNames": ["Device.DeviceInfo.SoftwareVersion"],
            }
            try:
                self._request_post(
                    endpoint=f"/devices/{quote(cpe_id)}/tasks",
                    data=gpv_task,
                    conn_request=True,
                    timeout=30,
                )
                success = True
                _LOGGER.info("Immediate connection request triggered for CPE %s", cpe_id)
            except Exception as exc:
                _LOGGER.error("Failed to trigger immediate connection: %s", exc)
                success = False
        else:
            target_time = datetime.now(timezone.utc) + timedelta(seconds=DelaySeconds)
            periodic_inform_time = target_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            success = bool(
                self.SPV(
                    param_value={
                        "Device.ManagementServer.PeriodicInformTime": periodic_inform_time
                    },
                    cpe_id=cpe_id,
                )
            )

        return [
            {
                "key": "ScheduleInform",
                "value": "1" if success else "0",
                "type": "boolean",
            }
        ]

    def GetRPCMethods(self, cpe_id: str | None = None) -> list[dict]:
        """Execute GetRPCMethods RPC."""
        raise NotImplementedError

    def Download(  # pylint: disable=too-many-arguments  # noqa: PLR0913
        self,
        url: str,
        filetype: str = "1 Firmware Upgrade Image",
        targetfilename: str = "",  # noqa: ARG002
        filesize: int = 200,  # noqa: ARG002
        username: str = "",
        password: str = "",
        commandkey: str = "",
        delayseconds: int = 0,
        successurl: str = "",  # noqa: ARG002
        failureurl: str = "",  # noqa: ARG002
        cpe_id: str | None = None,
    ) -> list[dict]:
        """Execute Download RPC via GenieACS NBI API."""
        cpe_id = cpe_id if cpe_id else self._cpeid
        if not cpe_id:
            msg = "cpe_id must be provided or set in device config"
            raise ValueError(msg)

        if not commandkey:
            commandkey = f"download-{int(time_now())}"

        if url:
            extracted_filename = url.split("/")[-1].split("?")[0]
        else:
            extracted_filename = "firmware.img"

        download_task: dict[str, Any] = {
            "name": "download",
            "fileType": filetype,
            "url": url,
            "commandKey": commandkey,
            "delaySeconds": delayseconds,
            "fileName": extracted_filename,
        }

        if filesize > 0:
            download_task["fileSize"] = filesize

        if username:
            download_task["username"] = username
        if password:
            download_task["password"] = password

        response_data = self._request_post(
            endpoint="/devices/" + quote(cpe_id) + "/tasks",
            data=download_task,
            conn_request=True,
            timeout=300,
        )

        _LOGGER.info("Download task created for CPE %s", cpe_id)

        if isinstance(response_data, dict):
            return [response_data]
        if isinstance(response_data, list):
            return response_data
        return []

    def provision_cpe_via_tr069(
        self,
        tr069provision_api_list: list[dict[str, list[dict[str, str]]]],
        cpe_id: str,
    ) -> None:
        """Provision the cable modem with tr069 parameters defined in env json."""
        cpe_id = cpe_id if (cpe_id == self._cpeid) else self._cpeid
        for tr069provision_api in tr069provision_api_list:
            for acs_api, params in tr069provision_api.items():
                api_function = getattr(self, acs_api)
                _ = [
                    retry_on_exception(
                        api_function,
                        (param, 30, cpe_id),
                        tout=60,
                        retries=3,
                    )
                    for param in params
                ]

    def delete_file(self, filename: str) -> None:
        """Delete the file from the device."""
        raise NotImplementedError

    def scp_device_file_to_local(self, local_path: str, source_path: str) -> None:
        """Copy a local file from a server using SCP."""
        raise NotImplementedError

    @property
    def firewall(self) -> IptablesFirewall:
        """Returns Firewall iptables instance."""
        raise NotImplementedError

    @property
    def ipv4_addr(self) -> str:
        """Return the IPv4 address."""
        raise NotImplementedError

    @property
    def ipv6_addr(self) -> str:
        """Return the IPv6 address."""
        raise NotImplementedError

    def start_tcpdump(
        self,
        interface: str,
        port: str | None,
        output_file: str = "pkt_capture.pcap",
        filters: dict | None = None,
        additional_filters: str | None = "",
    ) -> str:
        """Start tcpdump capture."""
        raise NotImplementedError

    def stop_tcpdump(self, process_id: str) -> None:
        """Stop tcpdump capture."""
        raise NotImplementedError


class GenieAcsGUI(ACSGUI):
    """GenieACS GUI Implementation."""

    def login(self) -> None:
        """Login to the ACS GUI."""
        pass


class GenieACS(LinuxDevice, ACS):
    """GenieACS connection class used to perform TR-069 operations."""

    def __init__(self, config: dict, cmdline_args: Namespace) -> None:
        """Initialize the variables that are used in establishing connection to the ACS."""
        super().__init__(config, cmdline_args)
        self._nbi = GenieAcsNBI(self)
        self._gui = GenieAcsGUI(self)

    @property
    def nbi(self) -> GenieAcsNBI:
        """ACS North Bound Interface."""
        return self._nbi

    @property
    def gui(self) -> GenieAcsGUI:
        """ACS GUI."""
        return self._gui

    @property
    def url(self) -> str:
        """Returns acs url used."""
        raise NotImplementedError

    @hookimpl
    def boardfarm_skip_boot(self) -> None:
        """Boardfarm hook implementation to skip boot the ITCProvisioner."""
        _LOGGER.info(
            "Initializing %s(%s) device with skip-boot option",
            self.device_name,
            self.device_type,
        )
        # Only connect console if SSH access is configured
        if self._config.get("ipaddr") and self._config.get("connection_type"):
            self._connect()
        self.nbi.initialize()

    @hookimpl
    def boardfarm_server_boot(self) -> None:
        """Boardfarm hook implementation to boot the ITCProvisioner."""
        _LOGGER.info("Booting %s(%s) device", self.device_name, self.device_type)
        # Only connect console if SSH access is configured
        if self._config.get("ipaddr") and self._config.get("connection_type"):
            self._connect()
        self.nbi.initialize()

    @hookimpl
    def boardfarm_shutdown_device(self) -> None:
        """Boardfarm hook implementation to shutdown ACS device."""
        _LOGGER.info("Shutdown %s(%s) device", self.device_name, self.device_type)
        self._disconnect()
        self.nbi.close()

    @hookimpl
    def contingency_check(self, env_req: dict[str, Any]) -> None:
        """Make sure ACS is able to read CPE/TR069 client params."""
        if self._cmdline_args.skip_contingency_checks or "tr-069" not in env_req.get(
            "environment_def",
            {},
        ):
            return
        _LOGGER.info("Contingency check %s(%s)", self.device_name, self.device_type)
        if not bool(
            retry_on_exception(
                self.nbi.GPV,
                ("Device.DeviceInfo.SoftwareVersion",),
                retries=10,
                tout=30,
            ),
        ):
            msg = "ACS service check Failed."
            raise ContingencyCheckError(msg)

    def scp_device_file_to_local(self, local_path: str, source_path: str) -> None:
        """Copy a local file from a server using SCP.

        :param local_path: local file path
        :param source_path: source path
        :raises NotImplementedError: missing implementation
        """
        raise NotImplementedError

    # TODO: This hack has to be done to make skip-boot a separate flow
    # The solution should be removed in the future and should not build upon
    def _add_cpe_id_to_acs_device(self, device_manager: DeviceManager) -> None:
        cpe = device_manager.get_device_by_type(CPE)  # type: ignore[type-abstract]
        if (
            not (oui := cpe.config.get("oui"))
            or not (product_class := cpe.config.get("product_class"))
            or not (serial := cpe.config.get("serial"))
        ):
            err_msg = "Inventory needs to have oui, product_class and serial entries!"
            raise BoardfarmException(err_msg)
        self._cpeid = f"{oui}-{product_class}-{serial}"

    @property
    def console(self) -> BoardfarmPexpect:
        """Returns ACS console.

        :return: console
        :rtype: BoardfarmPexpect
        :raises NotSupportedError: if the ACS does not have console access
        """
        if self._console is not None:
            return self._console
        msg = f"{self._config.get('name', 'GenieACS')} has no console access"
        raise NotSupportedError(msg)

    @property
    def firewall(self) -> IptablesFirewall:
        """Returns Firewall iptables instance.

        :raises NotSupportedError: does not support Firewall
        """
        raise NotSupportedError


if __name__ == "__main__":
    # stubbed instantation of the device
    # this would throw a linting issue in case the device does not follow the template
    GenieACS(config={}, cmdline_args=Namespace())
