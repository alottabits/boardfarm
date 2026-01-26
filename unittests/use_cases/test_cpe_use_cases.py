"""Unit tests for boardfarm3.use_cases.cpe module."""

import time
from unittest.mock import MagicMock, patch, call

import pytest

from boardfarm3.exceptions import UseCaseFailure
from boardfarm3.use_cases import cpe as cpe_use_cases
from boardfarm3.use_cases.cpe import (
    get_console_uptime_seconds,
    is_tr069_agent_running,
    refresh_console_connection,
    start_tr069_client,
    stop_tr069_client,
    wait_for_reboot_completion,
)


class TestGetConsoleUptimeSeconds:
    """Tests for get_console_uptime_seconds function."""

    def test_returns_uptime_from_sw(self, mock_cpe: MagicMock) -> None:
        """Test getting uptime from sw interface."""
        mock_cpe.sw.get_seconds_uptime.return_value = 7200
        
        result = get_console_uptime_seconds(mock_cpe)
        
        assert result == 7200
        mock_cpe.sw.get_seconds_uptime.assert_called_once()

    def test_fallback_to_hw_console(self, mock_cpe: MagicMock) -> None:
        """Test fallback to hw console when sw fails."""
        mock_cpe.sw.get_seconds_uptime.side_effect = Exception("sw failed")
        mock_console = MagicMock()
        # The command uses 'cut -d' ' -f1' so returns only the first field
        mock_console.execute_command.return_value = "3600.50"
        mock_cpe.hw.get_console.return_value = mock_console
        
        result = get_console_uptime_seconds(mock_cpe)
        
        assert result == 3600
        mock_cpe.hw.get_console.assert_called_with("console")

    def test_parses_proc_uptime_format(self, mock_cpe: MagicMock) -> None:
        """Test parsing /proc/uptime format correctly."""
        mock_cpe.sw.get_seconds_uptime.side_effect = Exception("sw failed")
        mock_console = MagicMock()
        # After cut -d' ' -f1, we get just the first number
        mock_console.execute_command.return_value = "12345.67"
        mock_cpe.hw.get_console.return_value = mock_console
        
        result = get_console_uptime_seconds(mock_cpe)
        
        assert result == 12345


class TestWaitForRebootCompletion:
    """Tests for wait_for_reboot_completion function.
    
    Note: This function raises UseCaseFailure on timeout/failure.
    """

    def test_detects_reboot_completion(self, mock_cpe: MagicMock) -> None:
        """Test detecting reboot when CPE becomes unresponsive then responsive."""
        mock_console = MagicMock()
        call_count = [0]
        
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            # Phase 1: First call succeeds, second fails (unresponsive)
            # Phase 2: Third call succeeds (responsive again)
            if call_count[0] == 1:
                return "test"  # Initial check - responsive
            if call_count[0] <= 3:
                raise Exception("Connection lost")  # Unresponsive
            return "test"  # Back online
        
        mock_console.execute_command.side_effect = side_effect
        mock_cpe.hw.get_console.return_value = mock_console
        
        with patch("time.sleep"):
            result = wait_for_reboot_completion(mock_cpe, timeout=60, poll_interval=1)
        
        assert result is True

    def test_raises_if_never_unresponsive(self, mock_cpe: MagicMock) -> None:
        """Test raises UseCaseFailure when CPE never becomes unresponsive."""
        mock_console = MagicMock()
        mock_console.execute_command.return_value = "test"  # Always responsive
        mock_cpe.hw.get_console.return_value = mock_console
        
        with patch("time.sleep"):
            with pytest.raises(UseCaseFailure, match="did not become unresponsive"):
                wait_for_reboot_completion(mock_cpe, timeout=4, poll_interval=1)

    def test_raises_if_never_responsive_after_reboot(
        self, mock_cpe: MagicMock
    ) -> None:
        """Test raises UseCaseFailure when CPE never comes back online."""
        mock_console = MagicMock()
        call_count = [0]
        
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return "test"  # Initial - responsive
            raise Exception("Connection lost")  # Never comes back
        
        mock_console.execute_command.side_effect = side_effect
        mock_cpe.hw.get_console.return_value = mock_console
        
        with patch("time.sleep"):
            with pytest.raises(UseCaseFailure, match="did not become responsive"):
                wait_for_reboot_completion(mock_cpe, timeout=4, poll_interval=1)


class TestStopTr069Client:
    """Tests for stop_tr069_client function."""

    def test_stops_cwmp_plugin(self, mock_cpe: MagicMock) -> None:
        """Test stopping the TR-069 client."""
        mock_console = MagicMock()
        mock_console.execute_command.side_effect = [
            "",  # stop command
            "",  # pgrep returns empty (process stopped)
        ]
        mock_cpe.hw.get_console.return_value = mock_console
        
        with patch("time.sleep"):
            stop_tr069_client(mock_cpe)
        
        # Verify stop command was called
        calls = mock_console.execute_command.call_args_list
        assert any("/etc/init.d/cwmp_plugin stop" in str(c) for c in calls)

    def test_raises_if_process_still_running(self, mock_cpe: MagicMock) -> None:
        """Test raises UseCaseFailure if process doesn't stop."""
        mock_console = MagicMock()
        mock_console.execute_command.side_effect = [
            "",  # stop command
            "12345",  # pgrep returns PID (still running)
        ]
        mock_cpe.hw.get_console.return_value = mock_console
        
        with patch("time.sleep"):
            with pytest.raises(UseCaseFailure, match="still running"):
                stop_tr069_client(mock_cpe)


class TestStartTr069Client:
    """Tests for start_tr069_client function."""

    def test_starts_cwmp_plugin(self, mock_cpe: MagicMock) -> None:
        """Test starting the TR-069 client."""
        mock_console = MagicMock()
        mock_console.execute_command.side_effect = [
            "",  # start command
            "12345",  # pgrep returns PID (process running)
        ]
        mock_cpe.hw.get_console.return_value = mock_console
        
        with patch("time.sleep"):
            start_tr069_client(mock_cpe)
        
        # Verify start command was called
        calls = mock_console.execute_command.call_args_list
        assert any("/etc/init.d/cwmp_plugin start" in str(c) for c in calls)

    def test_raises_if_process_not_started(self, mock_cpe: MagicMock) -> None:
        """Test raises UseCaseFailure if process doesn't start."""
        mock_console = MagicMock()
        mock_console.execute_command.side_effect = [
            "",  # start command
            "",  # pgrep returns empty (not running)
        ]
        mock_cpe.hw.get_console.return_value = mock_console
        
        with patch("time.sleep"):
            with pytest.raises(UseCaseFailure, match="failed to start"):
                start_tr069_client(mock_cpe)


class TestIsTr069AgentRunning:
    """Tests for is_tr069_agent_running function.
    
    Note: This function uses board.sw.is_tr069_connected() internally.
    """

    def test_returns_true_when_connected(self, mock_cpe: MagicMock) -> None:
        """Test returns True when TR-069 agent is connected."""
        mock_cpe.sw.is_tr069_connected.return_value = True
        
        result = is_tr069_agent_running(mock_cpe)
        
        assert result is True
        mock_cpe.sw.is_tr069_connected.assert_called_once()

    def test_returns_false_when_not_connected(self, mock_cpe: MagicMock) -> None:
        """Test returns False when TR-069 agent is not connected."""
        mock_cpe.sw.is_tr069_connected.return_value = False
        
        result = is_tr069_agent_running(mock_cpe)
        
        assert result is False


class TestRefreshConsoleConnection:
    """Tests for refresh_console_connection function."""

    def test_reconnects_console(self, mock_cpe: MagicMock) -> None:
        """Test refreshing console connection."""
        result = refresh_console_connection(mock_cpe)
        
        assert result is True
        mock_cpe.hw.disconnect_from_consoles.assert_called_once()
        mock_cpe.hw.connect_to_consoles.assert_called_once()

    def test_handles_disconnect_failure(self, mock_cpe: MagicMock) -> None:
        """Test handles disconnect failure gracefully."""
        mock_cpe.hw.disconnect_from_consoles.side_effect = Exception("Disconnect failed")
        
        result = refresh_console_connection(mock_cpe)
        
        # Should still try to connect
        assert result is True
        mock_cpe.hw.connect_to_consoles.assert_called_once()

    def test_returns_false_on_connect_failure(self, mock_cpe: MagicMock) -> None:
        """Test returns False when connect fails."""
        mock_cpe.hw.connect_to_consoles.side_effect = Exception("Connect failed")
        
        result = refresh_console_connection(mock_cpe)
        
        assert result is False

    def test_uses_device_name(self, mock_cpe: MagicMock) -> None:
        """Test uses device_name attribute."""
        mock_cpe.device_name = "custom_cpe"
        
        refresh_console_connection(mock_cpe)
        
        mock_cpe.hw.connect_to_consoles.assert_called_with("custom_cpe")


class TestVerifyConfigPreservation:
    """Tests for verify_config_preservation function."""

    def test_no_errors_when_config_matches(
        self, mock_cpe: MagicMock, mock_acs: MagicMock
    ) -> None:
        """Test no errors when configuration matches."""
        from boardfarm3.use_cases.cpe import verify_config_preservation
        
        # Mock nbi.GPV to return matching value (used by acs_use_cases internally)
        mock_acs.nbi.GPV.return_value = [{"value": "1.0.0"}]
        
        config_before = {
            "firmware_version": {
                "gpv_param": "Device.DeviceInfo.SoftwareVersion",
                "value": "1.0.0",
            }
        }
        
        errors = verify_config_preservation(mock_cpe, mock_acs, config_before)
        
        assert errors == []

    def test_detects_changed_value(
        self, mock_cpe: MagicMock, mock_acs: MagicMock
    ) -> None:
        """Test detects when value has changed."""
        from boardfarm3.use_cases.cpe import verify_config_preservation
        
        mock_acs.nbi.GPV.return_value = [{"value": "2.0.0"}]  # Changed
        
        config_before = {
            "firmware_version": {
                "gpv_param": "Device.DeviceInfo.SoftwareVersion",
                "value": "1.0.0",
            }
        }
        
        errors = verify_config_preservation(mock_cpe, mock_acs, config_before)
        
        assert len(errors) == 1
        assert "changed" in errors[0].lower()

    def test_handles_empty_config(
        self, mock_cpe: MagicMock, mock_acs: MagicMock
    ) -> None:
        """Test handles empty config with warning message."""
        from boardfarm3.use_cases.cpe import verify_config_preservation
        
        errors = verify_config_preservation(mock_cpe, mock_acs, {})
        
        # Returns warning message when config is empty
        assert len(errors) == 1
        assert "No configuration captured" in errors[0]
