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
from boardfarm3.templates.acs import ACS, GpvInput, GpvResponse, SpvInput
from boardfarm3.templates.cpe.cpe import CPE

if TYPE_CHECKING:
    from boardfarm3.lib.boardfarm_pexpect import BoardfarmPexpect
    from boardfarm3.lib.device_manager import DeviceManager
    from boardfarm3.lib.networking import IptablesFirewall

_DEFAULT_TIMEOUT = 60 * 2
_LOGGER = logging.getLogger(__name__)


# pylint:disable=R0801,too-many-public-methods
class GenieACS(LinuxDevice, ACS):
    """GenieACS connection class used to perform TR-069 operations."""

    CPE_wait_time = _DEFAULT_TIMEOUT

    def __init__(self, config: dict, cmdline_args: Namespace) -> None:
        """Initialize the variables that are used in establishing connection to the ACS.

        :param config: Boardfarm config
        :type config: dict
        :param cmdline_args: command line arguments
        :type cmdline_args: Namespace
        """
        self._disable_log_messages_from_libraries()
        super().__init__(config, cmdline_args)
        self._client: httpx.Client | None = None
        self._cpeid: str | None = None
        self._base_url: str | None = None

    def _disable_log_messages_from_libraries(self) -> None:
        """Disable logs from httpx."""
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)

    def _init_nbi_client(self) -> None:
        if self._client is None:
            self._base_url = (
                f"http://{self.config.get('ipaddr')}:{self.config.get('http_port')}"
            )
            self._client = httpx.Client(
                auth=(
                    self.config.get("http_username", "admin"),
                    self.config.get("http_password", "admin"),
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
        self._init_nbi_client()

    @hookimpl
    def boardfarm_server_boot(self) -> None:
        """Boardfarm hook implementation to boot the ITCProvisioner."""
        _LOGGER.info("Booting %s(%s) device", self.device_name, self.device_type)
        # Only connect console if SSH access is configured
        if self._config.get("ipaddr") and self._config.get("connection_type"):
            self._connect()
        self._init_nbi_client()

    @hookimpl
    def boardfarm_shutdown_device(self) -> None:
        """Boardfarm hook implementation to shutdown ACS device."""
        _LOGGER.info("Shutdown %s(%s) device", self.device_name, self.device_type)
        self._disconnect()
        self._client.close()

    # FIXME:I'm not a booting hook and I don't belong here!  # noqa: FIX001
    # BOARDFARM-4920
    @hookimpl
    def contingency_check(self, env_req: dict[str, Any]) -> None:
        """Make sure ACS is able to read CPE/TR069 client params.

        :param env_req: test env request
        :type env_req: dict[str, Any]
        :raises ContingencyCheckError: if CPE is not registered to ACS.
        """
        if self._cmdline_args.skip_contingency_checks or "tr-069" not in env_req.get(
            "environment_def",
            {},
        ):
            return
        _LOGGER.info("Contingency check %s(%s)", self.device_name, self.device_type)
        if not bool(
            retry_on_exception(
                self.GPV,
                ("Device.DeviceInfo.SoftwareVersion",),
                retries=10,
                tout=30,
            ),
        ):
            msg = "ACS service check Failed."
            raise ContingencyCheckError(msg)

    @property
    def url(self) -> str:
        """Returns acs url used.

        :raises NotImplementedError: missing implementation
        """
        raise NotImplementedError

    def GPA(self, param: str, cpe_id: str | None = None) -> list[dict]:
        """Execute GetParameterAttributes RPC call for the specified parameter.

        Example usage:

        >>> acs_server.GPA("Device.WiFi.SSID.1.SSID")

        :param param: parameter to be used in get
        :type param: str
        :param cpe_id: cpe identifier, defaults to None
        :type cpe_id: str | None
        :raises NotImplementedError: missing implementation
        """
        raise NotImplementedError

    def SPA(
        self,
        param: list[dict] | dict,
        notification_param: bool = True,
        access_param: bool = False,
        access_list: list | None = None,
        cpe_id: str | None = None,
    ) -> list[dict]:
        """Execute SetParameterAttributes RPC call for the specified parameter.

        Example usage:

        >>> (acs_server.SPA({"Device.WiFi.SSID.1.SSID": "1"}),)

        could be parameter list of dicts/dict containing param name and notifications

        :param param: parameter as key of dictionary and notification as its value
        :type param: list[dict] | dict
        :param notification_param: If True, the value of Notification replaces the
            current notification setting for this Parameter or group of Parameters.
            If False, no change is made to the notification setting
        :type notification_param: bool
        :param access_param: If True, the value of AccessList replaces the current
            access list for this Parameter or group of Parameters.
            If False, no change is made to the access list
        :type access_param: bool
        :param access_list: Array of zero or more entities for which write access to
            the specified Parameter(s) is granted
        :type access_list: list | None, optional
        :param cpe_id: cpe identifier, defaults to None
        :type cpe_id: str | None
        :raises NotImplementedError: missing implementation
        """
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
        """Send GetParamaterValues command via ACS server.

        :param param: TR069 parameters to get values of
        :type param: GpvInput
        :param timeout: wait time for the RPC to complete, defaults to None
        :type timeout: int | None, optional
        :param cpe_id: CPE identifier, defaults to None
        :type cpe_id: str | None, optional
        :return: GPV response with keys, value and datatype
        :rtype: GpvResponse
        """
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
                # Extract actual key-value pairs from the dictionary
                # Aligned with AxirosACS implementation
                for key, value in spv_params.items():
                    data.append([key, value])
            elif isinstance(spv_params, str) and isinstance(param_value, dict):
                data.append([spv_params, param_value[spv_params]])
        return {"name": "setParameterValues", "parameterValues": data}

    def _build_input_structs_download(
        self,
        url: str,
        filetype: str,
        targetfilename: str,
        filesize: int,
        username: str,
        password: str,
        commandkey: str,
        delayseconds: int,
        successurl: str,
        failureurl: str,
    ) -> dict[str, Any]:
        """Build Download task structure for GenieACS API.

        :param url: URL to download file
        :param filetype: File type string (e.g., "1 Firmware Upgrade Image")
        :param targetfilename: Target file name
        :param filesize: File size in bytes
        :param username: Username for authentication
        :param password: Password for authentication
        :param commandkey: Command key string
        :param delayseconds: Delay in seconds
        :param successurl: Success URL
        :param failureurl: Failure URL
        :return: Download task structure
        """
        # Build task dict with name and flattened parameters
        # GenieACS expects parameters at the top level, not nested
        # GenieACS uses camelCase for parameter names (not PascalCase)
        # GenieACS requires 'fileName' property (not 'targetFileName')
        # If targetfilename is not provided, extract filename from URL
        if not targetfilename and url:
            # Extract filename from URL
            # (e.g., "http://server/file.img" -> "file.img")
            targetfilename = url.split("/")[-1].split("?")[0]

        # Build task dict with required parameters
        # IMPORTANT: GenieACS vs PrplOS parameter compatibility issue
        # - GenieACS REQUIRES 'fileName' for task validation (rejects empty string)
        # - GenieACS includes 'fileSize' if provided (for validation)
        # - PrplOS ScheduleDownload does NOT support TargetFileName or FileSize
        #   (only supports: CommandKey, FileType, URL, Username, Password, DelaySeconds)
        # 
        # When GenieACS converts this task to TR-069 XML, it sends TargetFileName and FileSize
        # to PrplOS. According to TR-069 standards, CPEs should ignore unsupported parameters,
        # but PrplOS may reject the Download RPC if these parameters are present.
        #
        # Current workaround: Include fileName and fileSize for GenieACS validation.
        # If PrplOS rejects the Download RPC, this may need to be resolved via:
        # 1. GenieACS device-specific configuration (tags/presets) to omit parameters
        # 2. PrplOS update to ignore unsupported parameters per TR-069 standard
        # 3. GenieACS modification to support device-specific parameter filtering

        task: dict[str, Any] = {
            "name": "download",
            "fileType": filetype,
            "url": url,
            "commandKey": commandkey,
            "delaySeconds": delayseconds,
            "fileName": targetfilename,  # Required by GenieACS (may cause PrplOS rejection)
        }

        # Include fileSize for GenieACS validation (may cause PrplOS rejection)
        # GenieACS may validate fileSize, so include it if provided
        if filesize > 0:
            task["fileSize"] = filesize

        # Only include optional parameters if they have non-empty values
        # NOTE: successURL and failureURL are omitted for PrplOS compatibility
        # PrplOS ScheduleDownload only supports: CommandKey, FileType, URL, Username, Password, DelaySeconds
        if username:
            task["username"] = username
        if password:
            task["password"] = password

        return task

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
            timeout = timeout if timeout else GenieACS.CPE_wait_time
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

    def SPV(
        self,
        param_value: SpvInput,
        timeout: int | None = None,
        cpe_id: str | None = None,
    ) -> int:
        """Execute SetParameterValues RPC call for the specified parameter.

        :param param_value: dictionary that contains the path to the key and
            the value to be set. Example:
            .. code-block:: python

                {"Device.WiFi.AccessPoint.1.AC.1.Alias": "mok_1"}

        :type param_value: SpvInput
        :param timeout: wait time for the RPC to complete, defaults to None
        :type timeout: int | None
        :param cpe_id: CPE identifier, defaults to None
        :type cpe_id: str | None
        :return: status of the SPV, either 0 or 1
        :rtype: int
        """
        cpe_id = cpe_id if cpe_id else self._cpeid
        spv_data = self._build_input_structs_spv(param_value)
        response_data = self._request_post(
            endpoint="/devices/" + quote(cpe_id) + "/tasks",
            data=spv_data,
            conn_request=True,
            timeout=timeout,
        )
        # Return 0 for success (truthy response), 1 for failure (falsy response)
        # Aligned with AxirosACS implementation
        return 0 if response_data else 1

    def FactoryReset(self, cpe_id: str | None = None) -> list[dict]:
        """Execute FactoryReset RPC.

        Note: This method only informs if the FactoryReset request initiated or not.
        The wait for the reboot of the device has to be handled in the test.

        :param cpe_id: cpe identifier, defaults to None
        :type cpe_id: str | None
        :raises NotImplementedError: missing implementation
        """
        raise NotImplementedError

    def Reboot(
        self,
        CommandKey: str = "reboot",
        cpe_id: str | None = None,
    ) -> list[dict]:
        """Execute Reboot RPC via GenieACS NBI API.

        Creates a reboot task via GenieACS NBI API that matches the behavior of
        the "Reboot" button in the GenieACS UI. The task will be executed when
        the CPE checks in. The `conn_request=True` parameter triggers an immediate
        ConnectionRequest to the CPE, causing it to check in immediately rather
        than waiting for the next periodic check-in.

        This method sends:
        - Endpoint: POST /devices/{cpe_id}/tasks?connection_request=
        - Body: {"name": "reboot", "commandKey": CommandKey}

        :param CommandKey: reboot command key that will be returned in the
            CommandKey element of the InformStruct when the CPE reboots,
            defaults to "reboot"
        :type CommandKey: str
        :param cpe_id: cpe identifier, defaults to None
        :type cpe_id: str | None
        :return: reboot task creation response (empty list for compatibility)
        :rtype: list[dict]
        :raises ValueError: if cpe_id is not provided
        """
        if not cpe_id:
            raise ValueError("cpe_id is required for Reboot operation")

        # Create reboot task via GenieACS NBI API
        # Format matches exactly what the GenieACS UI sends when clicking "Reboot"
        reboot_task = {
            "name": "reboot",
            "commandKey": CommandKey,
        }

        # URL encode cpe_id to handle special characters (consistent with other methods)
        # The conn_request=True parameter adds ?connection_request= to trigger immediate
        # ConnectionRequest to the CPE
        self._request_post(
            endpoint="/devices/" + quote(cpe_id) + "/tasks",
            data=reboot_task,
            conn_request=True,
            timeout=30,
        )

        _LOGGER.info("Reboot task created for CPE %s (CommandKey: %s)", cpe_id, CommandKey)

        # Return empty list for compatibility with ACS template interface
        return []

    def AddObject(
        self,
        param: str,
        param_key: str = "",
        cpe_id: str | None = None,
    ) -> list[dict]:
        """Execute AddOjbect RPC call for the specified parameter.

        :param param: parameter to be used to add
        :type param: str
        :param param_key: the value to set the ParameterKey parameter, defaults to ""
        :type param_key: str
        :param cpe_id: cpe identifier, defaults to None
        :type cpe_id: str | None
        :raises NotImplementedError: missing implementation
        """
        raise NotImplementedError

    def DelObject(
        self,
        param: str,
        param_key: str = "",
        cpe_id: str | None = None,
    ) -> list[dict]:
        """Execute DeleteObject RPC call for the specified parameter.

        :param param: parameter to be used to delete
        :type param: str
        :param param_key: the value to set the ParameterKey parameter, defaults to ""
        :type param_key: str
        :param cpe_id: cpe identifier, defaults to None
        :type cpe_id: str | None
        :raises NotImplementedError: missing implementation
        """
        raise NotImplementedError

    def GPN(
        self,
        param: str,
        next_level: bool,
        timeout: int | None = None,
        cpe_id: str | None = None,
    ) -> list[dict]:
        """Execute GetParameterNames RPC call for the specified parameter.

        :param param: parameter to be discovered
        :type param: str
        :param next_level: displays the next level children of the object if marked true
        :type next_level: bool
        :param timeout: Lifetime Expiry time
        :type timeout: int | None
        :param cpe_id: cpe identifier, defaults to None
        :type cpe_id: str | None
        :raises NotImplementedError: missing implementation
        """
        raise NotImplementedError

    def ScheduleInform(
        self,
        CommandKey: str = "Test",  # noqa: ARG002
        DelaySeconds: int = 20,
        cpe_id: str | None = None,
    ) -> list[dict]:
        """Execute ScheduleInform RPC.

        **IMPORTANT**: GenieACS does NOT support `scheduleInform` as a task type via
        the NBI API. Unlike `reboot` and `download` tasks, ScheduleInform must be
        implemented using workarounds:

        - **Immediate inform (DelaySeconds=0)**: Creates a getParameterValues task with
          `?connection_request=` query parameter to trigger immediate ConnectionRequest.
          This forces the CPE to check in immediately and collect all pending tasks.
        - **Delayed inform (DelaySeconds>0)**: Sets PeriodicInformTime via SPV to
          schedule the CPE to check in at a future time.

        :param CommandKey: string to return in the CommandKey element of the
            InformStruct when the CPE calls the Inform method, defaults to "Test"
            Note: CommandKey is kept for API consistency with AxirosACS but
            is not used in GenieACS implementation (GenieACS workaround doesn't
            support CommandKey parameter)
        :type CommandKey: str
        :param DelaySeconds: number of seconds from the time this method is
            called to the time the CPE is requested to initiate a one-time Inform
            method call, defaults to 20
        :type DelaySeconds: int
        :param cpe_id: cpe identifier, defaults to None
        :type cpe_id: str | None, optional
        :return: ScheduleInform response
        :rtype: list[dict]
        """
        cpe_id = cpe_id if cpe_id else self._cpeid
        if not cpe_id:
            msg = "cpe_id must be provided or set in device config"
            raise ValueError(msg)

        if DelaySeconds == 0:
            # Trigger immediate connection by creating a getParameterValues task
            # with ?connection_request= parameter. This will cause GenieACS to
            # immediately send a ConnectionRequest to the CPE, triggering it to
            # check in and collect all pending tasks.
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
            # For delayed inform, set PeriodicInformTime
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
        """Execute GetRPCMethods RPC.

        :param cpe_id: cpe identifier, defaults to None
        :type cpe_id: str | None
        :raises NotImplementedError: missing implementation
        """
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
        """Execute Download RPC via GenieACS NBI API.

        Creates a download task and triggers immediate CPE connection via the
        `?connection_request=` parameter. This causes the CPE to check in immediately
        and collect the download task, rather than waiting for the next periodic check-in.

        :param url: URL to download file
        :type url: str
        :param filetype: the string parameter from following 6 values only

            .. code-block:: python

                [
                    "1 Firmware Upgrade Image",
                    "2 Web Content",
                    "3 Vendor Configuration File",
                    "4 Tone File",
                    "5 Ringer File",
                    "6 Stored Firmware Image",
                ]

        :type filetype: str
        :param targetfilename: TargetFileName to download through RPC (ignored)
        :type targetfilename: str
        :param filesize: the size of file to download in bytes (ignored)
        :type filesize: int
        :param username: User to authenticate with file Server. Default=""
        :type username: str
        :param password: Password to authenticate with file Server. Default=""
        :type password: str
        :param commandkey: the string parameter passed in Download API.
            If empty, auto-generated. Default=""
        :type commandkey: str
        :param delayseconds: delay of seconds in integer. Default=0
        :type delayseconds: int
        :param successurl: URL to access in case of Download API execution succeeded (ignored)
        :type successurl: str
        :param failureurl: URL to access in case of Download API execution failed (ignored)
        :type failureurl: str
        :param cpe_id: cpe identifier, defaults to None
        :type cpe_id: str | None
        :return: Download response
        :rtype: list[dict]
        """
        cpe_id = cpe_id if cpe_id else self._cpeid
        if not cpe_id:
            msg = "cpe_id must be provided or set in device config"
            raise ValueError(msg)

        # Generate CommandKey if not provided
        if not commandkey:
            commandkey = f"download-{int(time_now())}"

        # Extract filename from URL for fileName (required by GenieACS API)
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

        # Only include Username and Password if provided
        if username:
            download_task["username"] = username
        if password:
            download_task["password"] = password

        # Create Download task via GenieACS NBI API
        # The conn_request=True parameter triggers ?connection_request= which causes
        # GenieACS to immediately send a ConnectionRequest to the CPE, triggering
        # immediate check-in and task collection
        response_data = self._request_post(
            endpoint="/devices/" + quote(cpe_id) + "/tasks",
            data=download_task,
            conn_request=True,
            timeout=300,
        )

        _LOGGER.info("Download task created for CPE %s", cpe_id)

        # Convert response to list[dict] format
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
        """Provision the cable modem with tr069 parameters defined in env json.

        :param tr069provision_api_list: List of tr069 operations and their values
        :type tr069provision_api_list: list[dict[str, list[dict[str, str]]]]
        :param cpe_id: cpe identifier
        :type cpe_id: str
        """
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
        """Delete the file from the device.

        :param filename: name of the file with absolute path
        :type filename: str
        :raises NotImplementedError: missing implementation
        """
        raise NotImplementedError

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
