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
                data.append(
                    [
                        f"{iter(spv_params.keys())}",
                        iter(spv_params.values()),
                    ],
                )
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
            request_url = urljoin(self._base_url, f"{endpoint}?connection_request")
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
        return bool(response_data)

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
        """Execute Reboot RPC.

        :param CommandKey: reboot command key, defaults to "reboot"
        :type CommandKey: str
        :param cpe_id: cpe identifier, defaults to None
        :type cpe_id: str | None
        :raises NotImplementedError: missing implementation
        """
        raise NotImplementedError

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

        :param CommandKey: string to return in the CommandKey element of the
            InformStruct when the CPE calls the Inform method, defaults to "Test"
            Note: CommandKey is kept for API consistency with AxirosACS but
            is not used in GenieACS implementation
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

        # GenieACS doesn't support scheduleInform as a task name
        # For immediate inform (DelaySeconds=0), use GPV to trigger check-in
        # GPV creates a task with connection_request and queries the device
        # This is more reliable than just creating a dummy task because:
        # 1. GPV queries the device after creating the task, which may cause
        #    GenieACS to wait for the CPE to check in
        # 2. It's a real operation, not a dummy task
        # Note: ConnectionRequest should trigger immediate check-in, but it's
        # not guaranteed. The CPE should check in within 30 seconds.
        # For delayed inform, use SPV to set PeriodicInformTime
        if DelaySeconds == 0:
            # Trigger immediate connection via GPV
            # GPV creates a task with connection_request and queries the device
            # This should trigger the CPE to check in via ConnectionRequest
            try:
                # Use GPV to trigger check-in - it creates a task with connection_request
                # and queries the device, which may help ensure the CPE checks in
                self.GPV(
                    param=["Device.DeviceInfo.SoftwareVersion"],
                    timeout=30,
                    cpe_id=cpe_id,
                )
                success = True
            except (ConnectionError, ValueError, Exception):  # noqa: BLE001
                # If GPV fails, the CPE might not be responding to ConnectionRequest
                # This could mean:
                # 1. CPE is not reachable via ConnectionRequestURL
                # 2. CPE is busy with another session
                # 3. Network issues
                # We return False to indicate failure, but the task was created
                # so the CPE might still check in later
                success = False
        else:
            # For delayed inform, set PeriodicInformTime
            target_time = datetime.now(timezone.utc) + timedelta(
                seconds=DelaySeconds
            )
            # Format as ISO 8601 timestamp (TR-069 format)
            periodic_inform_time = target_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            success = bool(
                self.SPV(
                    param_value={
                        "Device.ManagementServer.PeriodicInformTime": (
                            periodic_inform_time
                        )
                    },
                    cpe_id=cpe_id,
                )
            )

        # Return response in format consistent with AxirosACS
        # AxirosACS returns list[dict] with details
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
        targetfilename: str = "",
        filesize: int = 200,  # noqa: ARG002
        username: str = "",
        password: str = "",
        commandkey: str = "",
        delayseconds: int = 0,
        successurl: str = "",  # noqa: ARG002
        failureurl: str = "",  # noqa: ARG002
        cpe_id: str | None = None,
    ) -> list[dict]:
        """Execute Download RPC.

        **PrplOS Compatibility:**
        After GenieACS patch, TargetFileName is only sent when non-empty,
        making this compatible with PrplOS which rejects empty TargetFileName.
        The patch ensures that when targetfilename is empty, GenieACS omits
        the TargetFileName parameter from the TR-069 XML entirely.

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
        :param targetfilename: TargetFileName to download through RPC.
            If empty, GenieACS will omit TargetFileName from TR-069 XML
            (after patch). Default=""
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
        :param delayseconds: delay of seconds in integer. Default=10
        :type delayseconds: int
        :param successurl: URL to access in case of Download API execution
            succeeded (ignored for PrplOS compatibility)
        :type successurl: str
        :param failureurl: URL to access in case of Download API execution
            Failed (ignored for PrplOS compatibility)
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

        # Extract filename from URL for fileName (required by GenieACS validation)
        # GenieACS requires fileName to be non-empty, so we always extract it from URL
        if url:
            extracted_filename = url.split("/")[-1].split("?")[0]
        else:
            extracted_filename = ""

        # Build Download task
        # NOTE: After GenieACS patch, TargetFileName is only sent when
        # non-empty. This makes it compatible with PrplOS which rejects
        # empty TargetFileName. We set:
        # - fileName: extracted from URL (required by GenieACS validation, must be non-empty)
        # - targetFileName: empty string (so patch omits it from TR-069 XML for PrplOS)
        download_task: dict[str, Any] = {
            "name": "download",
            "fileType": filetype,
            "url": url,
            "commandKey": commandkey,
            "delaySeconds": delayseconds,
            "fileName": extracted_filename,  # Required by GenieACS validation (must be non-empty)
            "targetFileName": "",  # Explicitly empty so patch omits it (PrplOS doesn't support TargetFileName)
        }

        # Only include Username and Password if provided
        if username:
            download_task["username"] = username
        if password:
            download_task["password"] = password

        # Debug: Log the Download task being sent
        _LOGGER.info(
            "Sending Download RPC to CPE %s with parameters: %s",
            cpe_id,
            {
                "fileType": filetype,
                "url": url,
                "commandKey": commandkey,
                "delaySeconds": delayseconds,
                "fileName": extracted_filename,
                "targetFileName": "",  # Empty - patch will omit from TR-069 XML
                "username": "***" if username else None,
                "password": "***" if password else None,
            },
        )

        # Post the Download task to GenieACS via NBI API
        # Use longer timeout for download operations
        timeout = 300  # 5 minutes default timeout

        # Verify device exists in GenieACS before creating task
        # This helps catch CPE ID mismatches early
        try:
            quoted_id = quote('{"_id":"' + cpe_id + '"}', safe="")
            device_check = self._request_get(
                endpoint=f'/devices?query={quoted_id}&projection={{"_id":1}}',
                timeout=10,
            )
            if isinstance(device_check, list) and len(device_check) == 0:
                _LOGGER.warning(
                    "Device with CPE ID %s not found in GenieACS. "
                    "Task creation may fail. Available devices may use different ID format.",
                    cpe_id,
                )
                # Try to list all available devices for debugging
                try:
                    all_devices = self._request_get(
                        endpoint='/devices?projection={"_id":1}',
                        timeout=10,
                    )
                    if isinstance(all_devices, list):
                        device_ids = [
                            d.get("_id")
                            for d in all_devices
                            if isinstance(d, dict) and d.get("_id")
                        ]
                        _LOGGER.warning(
                            "Available device IDs in GenieACS: %s",
                            device_ids,
                        )
                except Exception:  # noqa: BLE001
                    pass  # Ignore errors when listing devices
            elif isinstance(device_check, list) and len(device_check) > 0:
                actual_device_id = device_check[0].get("_id")
                if actual_device_id != cpe_id:
                    _LOGGER.warning(
                        "CPE ID mismatch: requested %s but GenieACS device has _id=%s. "
                        "Using actual GenieACS device ID for task creation.",
                        cpe_id,
                        actual_device_id,
                    )
                    # Use the actual device ID from GenieACS
                    cpe_id = actual_device_id
                else:
                    _LOGGER.debug(
                        "Verified device %s exists in GenieACS before creating Download task",
                        cpe_id,
                    )
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning(
                "Could not verify device existence for CPE %s: %s. "
                "Proceeding with task creation anyway.",
                cpe_id,
                e,
            )

        _LOGGER.debug(
            "Creating Download task for CPE %s via NBI API endpoint: /devices/%s/tasks",
            cpe_id,
            quote(cpe_id),
        )
        _LOGGER.debug("Download task payload: %s", download_task)

        try:
            response_data = self._request_post(
                endpoint="/devices/" + quote(cpe_id) + "/tasks",
                data=download_task,
                conn_request=True,
                timeout=timeout,
            )

            _LOGGER.info(
                "Download task created successfully for CPE %s. Response: %s",
                cpe_id,
                response_data,
            )
            _LOGGER.debug(
                "Full Download task creation response for CPE %s: %s",
                cpe_id,
                response_data,
            )

            # Verify task was created and assigned to the correct device
            try:
                # First, verify the device still exists and get its actual _id
                quoted_id = quote('{"_id":"' + cpe_id + '"}', safe="")
                device_check = self._request_get(
                    endpoint=f'/devices?query={quoted_id}&projection={{"_id":1}}',
                    timeout=10,
                )
                if isinstance(device_check, list) and len(device_check) > 0:
                    actual_device_id = device_check[0].get("_id")
                    if actual_device_id != cpe_id:
                        _LOGGER.error(
                            "CRITICAL: Task was created for CPE ID %s, but GenieACS device "
                            "has _id=%s. Task may be assigned to wrong device!",
                            cpe_id,
                            actual_device_id,
                        )
                    else:
                        _LOGGER.debug(
                            "Verified device %s exists in GenieACS after task creation",
                            cpe_id,
                        )
                else:
                    _LOGGER.error(
                        "CRITICAL: Device %s not found in GenieACS after task creation! "
                        "Task may have been created for a non-existent device.",
                        cpe_id,
                    )

                # Now verify the task exists for this device
                tasks_response = self._request_get(
                    endpoint="/devices/" + quote(cpe_id) + "/tasks",
                    timeout=10,
                )
                _LOGGER.debug(
                    "Current tasks for CPE %s: %s",
                    cpe_id,
                    tasks_response,
                )
                # Look for our Download task in the list
                if isinstance(tasks_response, list):
                    download_tasks = [
                        t
                        for t in tasks_response
                        if isinstance(t, dict)
                        and t.get("name") == "download"
                        and (
                            t.get("commandKey") == commandkey
                            or t.get("url") == url
                        )
                    ]
                    if download_tasks:
                        task_device_id = download_tasks[0].get("device")
                        if task_device_id and task_device_id != cpe_id:
                            _LOGGER.error(
                                "CRITICAL: Download task found but assigned to different device! "
                                "Task device: %s, Expected device: %s",
                                task_device_id,
                                cpe_id,
                            )
                        else:
                            _LOGGER.info(
                                "Verified Download task exists in GenieACS for CPE %s: %s",
                                cpe_id,
                                download_tasks[0],
                            )
                    else:
                        _LOGGER.warning(
                            "Download task not found in GenieACS task list for CPE %s. "
                            "Available tasks: %s",
                            cpe_id,
                            [t.get("name") for t in tasks_response if isinstance(t, dict)],
                        )
            except httpx.HTTPStatusError as exc:
                # Capture full HTTP error details
                error_msg = f"HTTP {exc.response.status_code}"
                try:
                    error_body = exc.response.json()
                    if isinstance(error_body, dict):
                        error_detail = (
                            error_body.get("error") or error_body.get("message")
                        )
                        if error_detail:
                            error_msg += f": {error_detail}"
                    elif isinstance(error_body, str):
                        error_msg += f": {error_body}"
                except ValueError:
                    error_msg += f": {exc.response.text[:200]}"
                _LOGGER.warning(
                    "Could not verify Download task creation for CPE %s: %s (URL: %s)",
                    cpe_id,
                    error_msg,
                    urljoin(self._base_url, "/devices/" + quote(cpe_id) + "/tasks"),
                )
            except httpx.ConnectError as exc:
                _LOGGER.warning(
                    "Could not connect to GenieACS to verify Download task for CPE %s: %s",
                    cpe_id,
                    exc,
                )
            except Exception as e:  # noqa: BLE001
                import traceback  # noqa: PLC0415

                _LOGGER.warning(
                    "Could not verify Download task creation for CPE %s: %s (Type: %s). "
                    "Traceback: %s",
                    cpe_id,
                    e,
                    type(e).__name__,
                    traceback.format_exc(),
                )

            # GenieACS returns task creation response
            # Convert to list[dict] format consistent with other RPC methods
            if isinstance(response_data, dict):
                return [response_data]
            if isinstance(response_data, list):
                return response_data
            # Fallback: return empty list if response format is unexpected
            return []
        except httpx.HTTPStatusError as exc:
            # Capture error details from response body
            error_msg = f"HTTP {exc.response.status_code}"
            try:
                error_body = exc.response.json()
                if isinstance(error_body, dict):
                    error_detail = (
                        error_body.get("error") or error_body.get("message")
                    )
                    if error_detail:
                        error_msg += f": {error_detail}"
                elif isinstance(error_body, str):
                    error_msg += f": {error_body}"
            except ValueError:
                # If response is not JSON, use raw text
                error_msg += f": {exc.response.text}"
            _LOGGER.error(
                "Failed to create Download task for CPE %s: %s",
                cpe_id,
                error_msg,
            )
            raise ConnectionError(error_msg) from exc
        except httpx.ConnectError as exc:
            _LOGGER.error(
                "Failed to connect to GenieACS for CPE %s: %s", cpe_id, exc
            )
            raise ConnectionError from exc

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
