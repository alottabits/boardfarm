"""GenieACS module."""

from __future__ import annotations

import logging
import time
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
    """GenieACS GUI Implementation using graph-based state machine navigation.
    
    This implementation uses:
    - Task-oriented methods from ACSGUI template
    - BaseGuiComponent with ui_map.json as single source of truth
    - Deterministic state tracking
    - Dynamic pathfinding for navigation
    - Config-driven optional initialization
    
    Configuration (optional, in boardfarm_config.json):
        gui_graph_file: Path to ui_map.json (single source of truth)
        gui_headless: Run browser in headless mode (default: true)
        gui_default_timeout: Element wait timeout in seconds (default: 20)
        
    Legacy Configuration (deprecated, Phase 2 migration):
        gui_selector_file: Path to selectors.yaml (no longer needed)
        gui_navigation_file: Path to navigation.yaml (no longer needed)
    """
    
    def __init__(self, device: GenieACS) -> None:
        """Initialize GenieACS GUI component.
        
        GUI initialization is deferred until initialize() is called.
        If GUI config is not provided, the component remains inactive.
        
        :param device: Parent GenieACS device
        """
        super().__init__(device)
        self._driver = None
        self._graph_component = None  # BaseGuiComponent instance
        
        # Read artifact path from config (optional)
        self._ui_graph_file = self.config.get("gui_graph_file")
        self._gui_base_url = self.config.get("gui_base_url")
        self._gui_timeout = self.config.get("gui_default_timeout", 20)
        
        # Auto-derive base URL if not explicitly set
        if not self._gui_base_url:
            port = self.config.get("gui_port", 3000)
            self._gui_base_url = (
                f"http://{self.config['ipaddr']}:{port}"
            )
    
    def is_gui_configured(self) -> bool:
        """Check if GUI testing is configured for this device.
        
        :return: True if UI graph file is configured
        """
        return bool(self._ui_graph_file)
    
    def is_initialized(self) -> bool:
        """Check if GUI component is initialized.
        
        :return: True if driver and graph component are ready
        """
        return bool(self._driver and self._graph_component)
    
    def initialize(self, driver=None) -> None:
        """Initialize GUI component with Selenium driver.
        
        Only initializes if UI graph file is configured in device config.
        Safe to call multiple times (idempotent).
        
        :param driver: Selenium WebDriver instance (creates ChromeDriver if None)
        :raises ValueError: If UI graph file not configured
        :raises FileNotFoundError: If UI graph file doesn't exist
        """
        # Check if already initialized
        if self.is_initialized():
            _LOGGER.debug("GUI already initialized, skipping")
            return
        
        # Check if GUI is configured
        if not self.is_gui_configured():
            err_msg = (
                f"GUI testing not configured for device "
                f"'{self.device.device_name}'. "
                f"To enable GUI testing, add to device config:\n"
                f"  'gui_graph_file': 'path/to/ui_map.json'\n\n"
                f"Generate UI map:\n"
                f"  python -m boardfarm3.lib.gui.ui_discovery \\\n"
                f"    --url {self._gui_base_url} \\\n"
                f"    --username admin --password admin \\\n"
                f"    --output ui_map.json"
            )
            raise ValueError(err_msg)
        
        # Create driver if not provided
        if driver is None:
            from selenium import webdriver
            options = webdriver.ChromeOptions()
            # Add headless mode for CI/CD
            if self.config.get("gui_headless", True):
                options.add_argument("--headless")
                options.add_argument("--no-sandbox")
                options.add_argument("--disable-dev-shm-usage")
            driver = webdriver.Chrome(options=options)
        
        self._driver = driver
        
        # Reduce Selenium's verbose logging (404s for element searches)
        self._configure_selenium_logging()
        
        # Initialize BaseGuiComponent with UI graph from config
        from boardfarm3.lib.gui.base_gui_component import BaseGuiComponent
        self._graph_component = BaseGuiComponent(
            driver=self._driver,
            ui_graph_file=self._ui_graph_file,
            default_timeout=self._gui_timeout
        )
        
        _LOGGER.info(
            "GenieACS GUI initialized with ui_graph=%s (%d pages, %d elements)",
            self._ui_graph_file,
            len(self._graph_component._pages),
            len(self._graph_component._elements)
        )
    
    def close(self) -> None:
        """Close GUI component and quit Selenium driver.
        
        Safe to call even if not initialized.
        """
        if self._driver:
            try:
                self._driver.quit()
            except Exception as e:
                _LOGGER.warning("Error closing Selenium driver: %s", e)
            finally:
                self._driver = None
                self._graph_component = None
    
    def _configure_selenium_logging(self) -> None:
        """Configure Selenium logging to reduce verbosity.
        
        Suppresses DEBUG-level 404 messages from element searches which
        are expected when trying multiple selectors in sequence.
        """
        # Reduce logging from Selenium's remote connection
        # This suppresses the verbose 404 responses when trying multiple selectors
        selenium_logger = logging.getLogger("selenium.webdriver.remote.remote_connection")
        selenium_logger.setLevel(logging.INFO)  # Only INFO and above
        
        _LOGGER.debug("Configured Selenium logging (remote_connection: INFO)")
    
    def _detect_current_page(self) -> str | None:
        """Detect which page we're currently on based on URL hash.
        
        GenieACS uses hash-based routing (#!/page_name), so we can
        determine the page from the URL. This allows us to use the
        appropriate selectors from selectors.yaml efficiently.
        
        :return: Page name matching selectors.yaml keys, or None if unknown
        """
        try:
            current_url = self._driver.current_url
            _LOGGER.debug("Detecting page from URL: %s", current_url)
            
            # GenieACS URL format: http://host:port/#!/page_name
            # Extract the hash fragment
            if "#!/" in current_url:
                hash_fragment = current_url.split("#!/")[1].split("?")[0]  # Remove query params
                
                # Map URL fragments to selectors.yaml page names
                page_mapping = {
                    "login": "login_page",
                    "overview": "home_page",
                    "devices": "device_list_page",
                    "faults": "faults_page",
                    "admin": "admin_page",
                    "admin/presets": "presets_page",
                    "admin/provisions": "provisions_page",
                    "admin/virtualParameters": "virtual_parameters_page",
                    "admin/files": "files_page",
                    "admin/config": "config_page",
                    "admin/permissions": "permissions_page",
                    "admin/users": "users_page",
                }
                
                # Check for device details (format: devices/ID)
                if hash_fragment.startswith("devices/") and "/" in hash_fragment:
                    return "device_details_page"
                
                # Direct mapping
                if hash_fragment in page_mapping:
                    page_name = page_mapping[hash_fragment]
                    _LOGGER.debug("Detected page: %s", page_name)
                    return page_name
                
                # Default for admin pages
                if hash_fragment.startswith("admin"):
                    _LOGGER.debug("Unknown admin page, defaulting to admin_page")
                    return "admin_page"
            
            # Default to home_page if we're logged in but URL unclear
            _LOGGER.debug("Could not detect specific page from URL")
            return None
            
        except Exception as e:
            _LOGGER.warning("Error detecting current page: %s", e)
            return None
    
    def _ensure_initialized(self) -> None:
        """Ensure Selenium driver and BaseGuiComponent are initialized.
        
        Provides helpful error message based on configuration state.
        
        :raises RuntimeError: If GUI component not initialized
        :raises ValueError: If GUI not configured
        """
        if not self.is_gui_configured():
            err_msg = (
                f"GUI testing not configured for device "
                f"'{self.device.device_name}'. "
                f"Add 'gui_graph_file' to device config."
            )
            raise ValueError(err_msg)

        if not self.is_initialized():
            err_msg = (
                f"GUI component not initialized for device "
                f"'{self.device.device_name}'. "
                f"Call gui.initialize() before using GUI methods."
            )
            raise RuntimeError(err_msg)
    
    # ========================================================================
    # Authentication Methods
    # ========================================================================
    
    def login(self, username: str | None = None, password: str | None = None) -> bool:
        """Login to GenieACS GUI using form-based authentication.
        
        Uses graph-based element finding with state tracking for deterministic navigation.
        
        :param username: Username (uses config if None)
        :param password: Password (uses config if None)
        :return: True if login successful
        """
        self._ensure_initialized()
        
        username = username or self.config.get("http_username", "admin")
        password = password or self.config.get("http_password", "admin")
        
        # Navigate to login page
        login_url = f"{self._gui_base_url}/#!/login"
        
        try:
            _LOGGER.info("Navigating to login page: %s", login_url)
            self._driver.get(login_url)
            
            # Set state to login_page
            self._graph_component.set_state('login_page', via_action='navigate')
            
            # Find and fill username input
            username_input = self._graph_component.find_element(
                'login_page',
                'username_input',
                timeout=self._gui_timeout
            )
            username_input.clear()
            username_input.send_keys(username)
            _LOGGER.debug("Entered username")
            
            # Find and fill password input
            password_input = self._graph_component.find_element(
                'login_page',
                'password_input',
                timeout=self._gui_timeout
            )
            password_input.clear()
            password_input.send_keys(password)
            _LOGGER.debug("Entered password")
            
            # Find and click login button
            login_btn = self._graph_component.find_element(
                'login_page',
                'login_button',
                timeout=self._gui_timeout
            )
            login_btn.click()
            _LOGGER.debug("Clicked login button")
            
            # Wait for redirect away from login page
            # Check that the username input disappears (proves we left login page)
            time.sleep(0.5)  # Brief initial wait for redirect to start
            
            for i in range(10):  # Up to 5 seconds total
                try:
                    # If we can still find username input, we're still on login page
                    self._graph_component.find_element('login_page', 'username_input', timeout=0.5)
                    time.sleep(0.5)
                except Exception:
                    # Username input gone - we've left login page!
                    _LOGGER.debug("Redirect complete, left login page")
                    break
            
            # Set state to home_page (we've successfully redirected away from login)
            self._graph_component.set_state('home_page', via_action='login_success')
            
            # Verify we can find the logout button on home page
            try:
                logout_btn = self._graph_component.find_element(
                    'home_page',
                    'log_out_button',
                    timeout=10
                )
                _LOGGER.info("Successfully logged into GenieACS GUI")
                return True
            except Exception as e:
                _LOGGER.error("Login verification failed - could not find logout button: %s", e)
                return False
            
        except Exception as e:
            _LOGGER.error("Login failed: %s", e)
            import traceback
            _LOGGER.debug("Login error traceback: %s", traceback.format_exc())
            return False
    
    def logout(self) -> bool:
        """Logout from GenieACS GUI.
        
        Uses state tracking to find the logout button on the current page,
        then clicks it and updates state to login_page.
        
        :return: True if logout successful
        """
        self._ensure_initialized()
        
        try:
            # Get current state
            current_state = self._graph_component.get_state()
            if not current_state:
                # Detect state from URL if not set
                current_url = self._driver.current_url
                if "#!/overview" in current_url:
                    current_state = "home_page"
                elif "#!/devices" in current_url and "#!/devices/" not in current_url:
                    current_state = "device_list_page"
                elif "#!/admin" in current_url:
                    current_state = "admin_page"
                else:
                    # Default to home_page as logout button is usually there
                    current_state = "home_page"
                
                self._graph_component.set_state(current_state, via_action='detected_from_url')
                _LOGGER.debug("Detected current state: %s", current_state)
            
            # Find logout button on current page
            logout_btn = self._graph_component.find_element(
                current_state,
                'log_out_button',
                timeout=self._gui_timeout
            )
            
            # Click logout button
            logout_btn.click()
            _LOGGER.debug("Clicked logout button")
            
            # Wait briefly for logout redirect
            time.sleep(0.5)
            
            # Update state to login_page
            self._graph_component.set_state('login_page', via_action='logout_success')
            
            _LOGGER.info("Successfully logged out from GenieACS GUI")
            return True
            
        except Exception as e:
            _LOGGER.error("Logout failed: %s", e)
            import traceback
            _LOGGER.debug("Logout error traceback: %s", traceback.format_exc())
            return False
    
    def is_logged_in(self) -> bool:
        """Check if currently logged into GenieACS GUI.
        
        Uses state tracking with validation: checks tracked state and verifies
        it matches reality using the verify_page() method.
        
        :return: True if logged in
        """
        self._ensure_initialized()
        
        try:
            current_url = self._driver.current_url
            _LOGGER.debug("Checking login status, current URL: %s", current_url)
            
            # 1. Blank/uninitialized browser = definitely not logged in
            if not current_url or current_url.startswith("data:") or current_url.startswith("about:"):
                _LOGGER.debug("Browser on blank page, not logged in")
                return False
            
            # 2. Check tracked state and validate it
            current_state = self._graph_component.get_state()
            
            if current_state == 'login_page':
                # Verify we're actually on login page
                if self._graph_component.verify_page('login_page', timeout=2, update_state=False):
                    _LOGGER.debug("Verified on login_page - not logged in")
                    return False
                else:
                    _LOGGER.warning("State is login_page but verification failed")
                    return False
                    
            elif current_state is not None:
                # State indicates logged in - verify we're on that page
                if self._graph_component.verify_page(current_state, timeout=2, update_state=False):
                    _LOGGER.debug("Verified on %s - logged in", current_state)
                    return True
                else:
                    _LOGGER.warning("State is %s but verification failed", current_state)
                    # Fall through to URL check
                    
            # 3. No state or validation failed - check URL as fallback
            if "/#!/login" in current_url:
                _LOGGER.debug("URL indicates login page, not logged in")
                return False
            elif self._gui_base_url in current_url:
                _LOGGER.debug("URL indicates GenieACS (not login), assuming logged in")
                return True
            else:
                _LOGGER.debug("Unknown state and URL, assuming not logged in")
                return False
            
        except Exception as e:
            _LOGGER.warning("Error checking login status: %s", e)
            return False
    
    # ========================================================================
    # Device Discovery & Navigation Methods
    # ========================================================================
    
    def search_device(self, cpe_id: str) -> bool:
        """Search for device in GenieACS by CPE ID.
        
        :param cpe_id: CPE identifier (serial number or ID)
        :return: True if device found
        """
        self._ensure_initialized()
        
        # Navigate to devices page (uses navigation.yaml)
        self._base_component.navigate_path("Path_Home_to_Devices")
        
        # Find search input
        search_input = self._base_component.find_element_by_function(
            element_type="input",
            function_keywords=["search", "filter", "find"],
            page="devices_page",
            fallback_name="device_search"
        )
        search_input.clear()
        search_input.send_keys(cpe_id)
        
        # Optionally trigger search (some UIs need button click, others are live search)
        try:
            search_btn = self._base_component.find_element_by_function(
                element_type="button",
                function_keywords=["search", "find", "go"],
                page="devices_page",
                timeout=2
            )
            search_btn.click()
        except Exception:
            pass  # Live search, no button needed
        
        # Check if device appears in results
        try:
            # Look for device link/row containing the CPE ID
            device_link = self._base_component._find_element(
                f"devices_page.links.device_{cpe_id}",
                timeout=self._gui_timeout
            )
            return device_link is not None
        except Exception as e:
            _LOGGER.debug("Device %s not found: %s", cpe_id, e)
            return False
    
    def get_device_count(self) -> int:
        """Get total number of devices in GenieACS.
        
        :return: Number of devices
        """
        self._ensure_initialized()
        
        # Navigate to devices page
        self._base_component.navigate_path("Path_Home_to_Devices")
        
        # GenieACS typically shows count in pagination or summary
        try:
            count_element = self._base_component.find_element_by_function(
                element_type="button",  # Could be span, div, etc.
                function_keywords=["total", "count", "devices", "showing"],
                page="devices_page",
                timeout=5
            )
            # Extract number from text (e.g., "Showing 1-20 of 150")
            text = count_element.text
            # Parse count from text (implementation depends on UI format)
            import re
            match = re.search(r'of\s+(\d+)', text, re.IGNORECASE)
            if match:
                return int(match.group(1))
            return 0
        except Exception as e:
            _LOGGER.error("Failed to get device count: %s", e)
            return 0
    
    def filter_devices(self, filter_criteria: dict[str, str]) -> int:
        """Apply filter criteria to device list.
        
        :param filter_criteria: Dict of field:value filters
        :return: Number of devices matching filter
        """
        self._ensure_initialized()
        
        # Navigate to devices page
        self._base_component.navigate_path("Path_Home_to_Devices")
        
        # GenieACS uses query builder for filtering
        # This is a simplified implementation
        for field, value in filter_criteria.items():
            # Find filter input for this field
            filter_input = self._base_component.find_element_by_function(
                element_type="input",
                function_keywords=["filter", field, "query"],
                page="devices_page"
            )
            filter_input.clear()
            filter_input.send_keys(f"{field}:{value}")
        
        # Apply filter
        apply_btn = self._base_component.find_element_by_function(
            element_type="button",
            function_keywords=["apply", "filter", "search"],
            page="devices_page"
        )
        apply_btn.click()
        
        # Return count after filtering
        return self.get_device_count()
    
    # ========================================================================
    # Device Status & Information Methods
    # ========================================================================
    
    def get_device_status(self, cpe_id: str) -> dict[str, str]:
        """Get device status from GenieACS GUI.
        
        :param cpe_id: CPE identifier
        :return: Dict with status info
        """
        self._ensure_initialized()
        
        # Navigate to device details
        self._base_component.navigate_path(
            "Path_Devices_to_DeviceDetails",
            cpe_id=cpe_id
        )
        
        # Extract status information from UI
        # GenieACS shows status in overview/summary section
        status_info = {}
        
        try:
            # Get online/offline status
            status_element = self._base_component.find_element_by_function(
                element_type="button",  # Could be span, badge, etc.
                function_keywords=["status", "online", "connected"],
                page="device_details_page",
                timeout=5
            )
            status_info["status"] = status_element.text.lower()
        except Exception:
            status_info["status"] = "unknown"
        
        # Additional fields can be extracted similarly
        return status_info
    
    def verify_device_online(self, cpe_id: str, timeout: int = 60) -> bool:
        """Wait for device to come online.
        
        :param cpe_id: CPE identifier
        :param timeout: Max wait time in seconds
        :return: True if device comes online
        """
        self._ensure_initialized()
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            status = self.get_device_status(cpe_id)
            if status.get("status") == "online":
                return True
            time.sleep(5)  # Check every 5 seconds
        
        return False
    
    def get_last_inform_time(self, cpe_id: str) -> str:
        """Get device's last inform timestamp.
        
        :param cpe_id: CPE identifier
        :return: Last inform time (ISO format)
        """
        self._ensure_initialized()
        
        # Navigate to device details
        self._base_component.navigate_path(
            "Path_Devices_to_DeviceDetails",
            cpe_id=cpe_id
        )
        
        # Find last inform element
        try:
            inform_element = self._base_component.find_element_by_function(
                element_type="button",  # Could be span, div, etc.
                function_keywords=["last", "inform", "contact", "connection"],
                page="device_details_page"
            )
            return inform_element.text
        except Exception as e:
            _LOGGER.error("Failed to get last inform time: %s", e)
            return ""
    
    # ========================================================================
    # Device Operation Methods
    # ========================================================================
    
    def reboot_device_via_gui(self, cpe_id: str) -> bool:
        """Reboot device via GenieACS GUI.
        
        :param cpe_id: CPE identifier
        :return: True if reboot initiated
        """
        self._ensure_initialized()
        
        # Navigate to device details
        self._base_component.navigate_path(
            "Path_Devices_to_DeviceDetails",
            cpe_id=cpe_id
        )
        
        # Find reboot button using semantic search
        reboot_btn = self._base_component.find_element_by_function(
            element_type="button",
            function_keywords=["reboot", "restart", "reset"],
            page="device_details_page",
            fallback_name="reboot"
        )
        reboot_btn.click()
        
        # Handle confirmation modal if present
        try:
            confirm_btn = self._base_component.find_element_by_function(
                element_type="button",
                function_keywords=["confirm", "yes", "ok", "proceed"],
                page="reboot_modal",
                timeout=2
            )
            confirm_btn.click()
        except Exception:
            pass  # No confirmation needed
        
        _LOGGER.info("Reboot initiated for device %s", cpe_id)
        return True
    
    def factory_reset_via_gui(self, cpe_id: str) -> bool:
        """Factory reset device via GenieACS GUI.
        
        :param cpe_id: CPE identifier
        :return: True if factory reset initiated
        """
        self._ensure_initialized()
        
        # Navigate to device details
        self._base_component.navigate_path(
            "Path_Devices_to_DeviceDetails",
            cpe_id=cpe_id
        )
        
        # Find factory reset button
        reset_btn = self._base_component.find_element_by_function(
            element_type="button",
            function_keywords=["factory", "reset", "default"],
            page="device_details_page",
            fallback_name="factory_reset"
        )
        reset_btn.click()
        
        # Confirm (factory reset usually requires confirmation)
        try:
            confirm_btn = self._base_component.find_element_by_function(
                element_type="button",
                function_keywords=["confirm", "yes", "proceed"],
                page="factory_reset_modal",
                timeout=5
            )
            confirm_btn.click()
        except Exception as e:
            _LOGGER.error("Factory reset confirmation failed: %s", e)
            return False
        
        _LOGGER.info("Factory reset initiated for device %s", cpe_id)
        return True
    
    def delete_device_via_gui(self, cpe_id: str, confirm: bool = True) -> bool:
        """Delete device from GenieACS via GUI.
        
        :param cpe_id: CPE identifier
        :param confirm: Whether to confirm deletion
        :return: True if deletion successful
        """
        self._ensure_initialized()
        
        # Navigate to device details
        self._base_component.navigate_path(
            "Path_Devices_to_DeviceDetails",
            cpe_id=cpe_id
        )
        
        # Find delete button
        delete_btn = self._base_component.find_element_by_function(
            element_type="button",
            function_keywords=["delete", "remove"],
            page="device_details_page",
            fallback_name="delete"
        )
        delete_btn.click()
        
        if confirm:
            try:
                confirm_btn = self._base_component.find_element_by_function(
                    element_type="button",
                    function_keywords=["confirm", "yes", "delete"],
                    page="delete_modal",
                    timeout=5
                )
                confirm_btn.click()
            except Exception as e:
                _LOGGER.error("Delete confirmation failed: %s", e)
                return False
        
        _LOGGER.info("Device %s deleted", cpe_id)
        return True
    
    # ========================================================================
    # Parameter Operation Methods
    # ========================================================================
    
    def get_device_parameter_via_gui(self, cpe_id: str, parameter: str) -> str | None:
        """Get device parameter value via GUI.
        
        :param cpe_id: CPE identifier
        :param parameter: TR-069 parameter path
        :return: Parameter value or None
        """
        self._ensure_initialized()
        
        # Navigate to device parameters page
        self._base_component.navigate_path(
            "Path_Devices_to_Parameters",
            cpe_id=cpe_id
        )
        
        # Search for parameter
        search_input = self._base_component.find_element_by_function(
            element_type="input",
            function_keywords=["search", "filter", "parameter"],
            page="parameters_page"
        )
        search_input.clear()
        search_input.send_keys(parameter)
        
        # Get value from table/list
        # Implementation depends on GenieACS UI structure
        try:
            # This is a simplified version
            value_element = self._base_component._find_element(
                f"parameters_page.values.{parameter}",
                timeout=self._gui_timeout
            )
            return value_element.text
        except Exception as e:
            _LOGGER.error("Failed to get parameter %s: %s", parameter, e)
            return None
    
    def set_device_parameter_via_gui(
        self, cpe_id: str, parameter: str, value: str
    ) -> bool:
        """Set device parameter via GUI.
        
        :param cpe_id: CPE identifier
        :param parameter: TR-069 parameter path
        :param value: Value to set
        :return: True if successful
        """
        self._ensure_initialized()
        
        # Navigate to device parameters page
        self._base_component.navigate_path(
            "Path_Devices_to_Parameters",
            cpe_id=cpe_id
        )
        
        # Find parameter and edit
        # GenieACS typically has edit buttons or inline editing
        try:
            edit_btn = self._base_component.find_element_by_function(
                element_type="button",
                function_keywords=["edit", "modify", "change"],
                page="parameters_page"
            )
            edit_btn.click()
            
            # Enter new value
            value_input = self._base_component.find_element_by_function(
                element_type="input",
                function_keywords=["value", parameter],
                page="edit_parameter_modal"
            )
            value_input.clear()
            value_input.send_keys(value)
            
            # Save
            save_btn = self._base_component.find_element_by_function(
                element_type="button",
                function_keywords=["save", "apply", "submit"],
                page="edit_parameter_modal"
            )
            save_btn.click()
            
            _LOGGER.info("Parameter %s set to %s", parameter, value)
            return True
        except Exception as e:
            _LOGGER.error("Failed to set parameter %s: %s", parameter, e)
            return False
    
    # ========================================================================
    # Firmware Operation Methods
    # ========================================================================
    
    def trigger_firmware_upgrade_via_gui(self, cpe_id: str, firmware_url: str) -> bool:
        """Trigger firmware upgrade via GUI.
        
        :param cpe_id: CPE identifier
        :param firmware_url: URL of firmware image
        :return: True if upgrade initiated
        """
        self._ensure_initialized()
        
        # Navigate to device details
        self._base_component.navigate_path(
            "Path_Devices_to_DeviceDetails",
            cpe_id=cpe_id
        )
        
        # Find firmware/upgrade section
        upgrade_btn = self._base_component.find_element_by_function(
            element_type="button",
            function_keywords=["firmware", "upgrade", "update"],
            page="device_details_page",
            fallback_name="firmware_upgrade"
        )
        upgrade_btn.click()
        
        # Enter firmware URL
        url_input = self._base_component.find_element_by_function(
            element_type="input",
            function_keywords=["url", "firmware", "file"],
            page="firmware_modal"
        )
        url_input.clear()
        url_input.send_keys(firmware_url)
        
        # Trigger upgrade
        start_btn = self._base_component.find_element_by_function(
            element_type="button",
            function_keywords=["start", "upgrade", "download"],
            page="firmware_modal"
        )
        start_btn.click()
        
        _LOGGER.info("Firmware upgrade initiated for %s", cpe_id)
        return True
    
    def verify_firmware_version_via_gui(
        self, cpe_id: str, expected_version: str
    ) -> bool:
        """Verify firmware version via GUI.
        
        :param cpe_id: CPE identifier
        :param expected_version: Expected firmware version
        :return: True if version matches
        """
        self._ensure_initialized()
        
        # Navigate to device details
        self._base_component.navigate_path(
            "Path_Devices_to_DeviceDetails",
            cpe_id=cpe_id
        )
        
        # Find firmware version display
        try:
            version_element = self._base_component.find_element_by_function(
                element_type="button",  # Could be span, div, etc.
                function_keywords=["firmware", "version", "software"],
                page="device_details_page"
            )
            current_version = version_element.text
            return expected_version in current_version
        except Exception as e:
            _LOGGER.error("Failed to verify firmware version: %s", e)
            return False


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
        """Boardfarm hook implementation to skip boot the GenieACS."""
        _LOGGER.info(
            "Initializing %s(%s) device with skip-boot option",
            self.device_name,
            self.device_type,
        )
        # Only connect console if SSH access is configured
        if self._config.get("ipaddr") and self._config.get("connection_type"):
            self._connect()
        
        # Always initialize NBI
        self.nbi.initialize()
        
        # Optionally initialize GUI (only if configured)
        if self.gui.is_gui_configured():
            try:
                self.gui.initialize()
                _LOGGER.info("GUI component initialized successfully")
            except Exception as e:
                _LOGGER.warning(
                    "GUI initialization failed (continuing without GUI): %s", e
                )
        else:
            _LOGGER.debug("GUI not configured, skipping GUI initialization")

    @hookimpl
    def boardfarm_server_boot(self) -> None:
        """Boardfarm hook implementation to boot the GenieACS."""
        _LOGGER.info("Booting %s(%s) device", self.device_name, self.device_type)
        # Only connect console if SSH access is configured
        if self._config.get("ipaddr") and self._config.get("connection_type"):
            self._connect()
        
        # Always initialize NBI
        self.nbi.initialize()
        
        # Optionally initialize GUI (only if configured)
        if self.gui.is_gui_configured():
            try:
                self.gui.initialize()
                _LOGGER.info("GUI component initialized successfully")
            except Exception as e:
                _LOGGER.warning(
                    "GUI initialization failed (continuing without GUI): %s", e
                )
        else:
            _LOGGER.debug("GUI not configured, skipping GUI initialization")

    @hookimpl
    def boardfarm_shutdown_device(self) -> None:
        """Boardfarm hook implementation to shutdown ACS device."""
        _LOGGER.info("Shutdown %s(%s) device", self.device_name, self.device_type)
        self._disconnect()
        self.nbi.close()
        self.gui.close()  # Safe to call even if not initialized

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
