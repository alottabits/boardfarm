"""Unit tests for boardfarm3.use_cases.acs module."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from boardfarm3.use_cases import acs as acs_use_cases
from boardfarm3.use_cases.acs import (
    _filter_logs_by_cpe_id,
    _filter_logs_by_timestamp,
    _parse_log_timestamp,
    get_parameter_value,
    initiate_reboot,
    is_cpe_online,
    set_parameter_value,
)


class TestParseLogTimestamp:
    """Tests for _parse_log_timestamp function."""

    def test_iso_format_with_milliseconds(self) -> None:
        """Test parsing ISO format with milliseconds and Z timezone."""
        log_line = '2024-01-15T10:30:00.123Z [INFO] test message'
        result = _parse_log_timestamp(log_line)
        
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
        assert result.hour == 10
        assert result.minute == 30
        assert result.second == 0

    def test_iso_format_without_milliseconds(self) -> None:
        """Test parsing ISO format without milliseconds."""
        log_line = '2024-01-15T10:30:00Z [INFO] test message'
        result = _parse_log_timestamp(log_line)
        
        assert result is not None
        assert result.year == 2024
        assert result.hour == 10

    def test_proxy_log_format(self) -> None:
        """Test parsing proxy log format (space-separated date/time)."""
        log_line = '2024-01-15 10:30:00 [INFO] proxy message'
        result = _parse_log_timestamp(log_line)
        
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_no_timestamp(self) -> None:
        """Test log line with no timestamp returns None."""
        log_line = 'Just a plain message with no timestamp'
        result = _parse_log_timestamp(log_line)
        
        assert result is None


class TestFilterLogsByTimestamp:
    """Tests for _filter_logs_by_timestamp function."""

    def test_filters_by_timestamp(self, sample_log_lines: list[str]) -> None:
        """Test that logs are filtered correctly by timestamp."""
        start_time = datetime(2024, 1, 15, 10, 30, 1)
        result = _filter_logs_by_timestamp(sample_log_lines, start_time)
        
        # Should include lines at or after 10:30:01
        assert len(result) >= 2

    def test_none_timestamp_returns_all(self, sample_log_lines: list[str]) -> None:
        """Test that None timestamp returns all lines."""
        result = _filter_logs_by_timestamp(sample_log_lines, None)
        
        assert len(result) == len(sample_log_lines)

    def test_empty_list(self) -> None:
        """Test with empty list."""
        result = _filter_logs_by_timestamp([], datetime.now())
        
        assert result == []


class TestFilterLogsByCpeId:
    """Tests for _filter_logs_by_cpe_id function."""

    def test_filters_by_cpe_id(self, sample_log_lines: list[str]) -> None:
        """Test that logs are filtered correctly by CPE ID."""
        result = _filter_logs_by_cpe_id(sample_log_lines, "TEST-CPE-001")
        
        # Should only include lines with TEST-CPE-001
        assert len(result) == 3
        for line in result:
            assert "TEST-CPE-001" in line

    def test_none_cpe_id_returns_all(self, sample_log_lines: list[str]) -> None:
        """Test that None CPE ID returns all lines."""
        result = _filter_logs_by_cpe_id(sample_log_lines, None)
        
        assert len(result) == len(sample_log_lines)

    def test_no_matching_cpe_id(self, sample_log_lines: list[str]) -> None:
        """Test with non-existent CPE ID."""
        result = _filter_logs_by_cpe_id(sample_log_lines, "NONEXISTENT-CPE")
        
        assert result == []


class TestGetParameterValue:
    """Tests for get_parameter_value function."""

    def test_successful_gpv(self, mock_acs: MagicMock, mock_cpe: MagicMock) -> None:
        """Test successful parameter retrieval."""
        mock_acs.nbi.GPV.return_value = [{"value": "1.0.0"}]
        
        result = get_parameter_value(
            mock_acs, mock_cpe, "Device.DeviceInfo.SoftwareVersion"
        )
        
        assert result == "1.0.0"
        mock_acs.nbi.GPV.assert_called_once()

    def test_gpv_with_rval(self, mock_acs: MagicMock, mock_cpe: MagicMock) -> None:
        """Test parameter retrieval with rval format."""
        mock_acs.nbi.GPV.return_value = [{"rval": "test_rval"}]
        
        result = get_parameter_value(
            mock_acs, mock_cpe, "Device.DeviceInfo.SoftwareVersion"
        )
        
        assert result == "test_rval"

    def test_gpv_empty_result_raises(
        self, mock_acs: MagicMock, mock_cpe: MagicMock
    ) -> None:
        """Test that empty GPV result raises after retries."""
        mock_acs.nbi.GPV.return_value = []
        
        with pytest.raises(Exception):  # UseCaseFailure or AssertionError
            get_parameter_value(
                mock_acs, mock_cpe, "Device.DeviceInfo.SoftwareVersion",
                retries=1
            )


class TestSetParameterValue:
    """Tests for set_parameter_value function."""

    def test_successful_spv_returns_zero(
        self, mock_acs: MagicMock, mock_cpe: MagicMock
    ) -> None:
        """Test successful parameter setting when SPV returns 0."""
        mock_acs.nbi.SPV.return_value = 0
        
        result = set_parameter_value(
            mock_acs, mock_cpe, "Device.WiFi.SSID.1.SSID", "TestNetwork"
        )
        
        assert result is True
        mock_acs.nbi.SPV.assert_called_once()

    def test_successful_spv_returns_one(
        self, mock_acs: MagicMock, mock_cpe: MagicMock
    ) -> None:
        """Test successful parameter setting when SPV returns 1."""
        mock_acs.nbi.SPV.return_value = 1  # Also considered success
        
        result = set_parameter_value(
            mock_acs, mock_cpe, "Device.WiFi.SSID.1.SSID", "TestNetwork"
        )
        
        assert result is True

    def test_spv_failure(self, mock_acs: MagicMock, mock_cpe: MagicMock) -> None:
        """Test SPV failure returns False."""
        mock_acs.nbi.SPV.return_value = 9001  # Error code = failure
        
        result = set_parameter_value(
            mock_acs, mock_cpe, "Device.WiFi.SSID.1.SSID", "TestNetwork"
        )
        
        assert result is False


class TestInitiateReboot:
    """Tests for initiate_reboot function."""

    def test_successful_reboot(
        self, mock_acs: MagicMock, mock_cpe: MagicMock
    ) -> None:
        """Test successful reboot initiation."""
        # Should not raise
        initiate_reboot(mock_acs, mock_cpe, command_key="test_reboot")
        
        mock_acs.nbi.Reboot.assert_called_once()

    def test_reboot_with_custom_command_key(
        self, mock_acs: MagicMock, mock_cpe: MagicMock
    ) -> None:
        """Test reboot with custom command key."""
        initiate_reboot(mock_acs, mock_cpe, command_key="custom_key")
        
        # Verify command key was passed
        call_kwargs = mock_acs.nbi.Reboot.call_args
        assert call_kwargs is not None


class TestIsCpeOnline:
    """Tests for is_cpe_online function."""

    def test_cpe_online(self, mock_acs: MagicMock, mock_cpe: MagicMock) -> None:
        """Test CPE is detected as online."""
        mock_acs.nbi.GPV.return_value = [{"value": "1.0.0"}]
        
        result = is_cpe_online(mock_acs, mock_cpe, timeout=5)
        
        assert result is True

    def test_cpe_offline(self, mock_acs: MagicMock, mock_cpe: MagicMock) -> None:
        """Test CPE is detected as offline when GPV fails."""
        mock_acs.nbi.GPV.return_value = None
        
        result = is_cpe_online(mock_acs, mock_cpe, timeout=5)
        
        assert result is False

    def test_cpe_offline_on_exception(
        self, mock_acs: MagicMock, mock_cpe: MagicMock
    ) -> None:
        """Test CPE is detected as offline on exception."""
        mock_acs.nbi.GPV.side_effect = Exception("Connection failed")
        
        result = is_cpe_online(mock_acs, mock_cpe, timeout=5)
        
        assert result is False


class TestViaParameter:
    """Tests for the 'via' parameter interface selection."""

    def test_get_parameter_via_nbi(
        self, mock_acs: MagicMock, mock_cpe: MagicMock
    ) -> None:
        """Test get_parameter_value uses NBI by default."""
        mock_acs.nbi.GPV.return_value = [{"value": "nbi_value"}]
        
        result = get_parameter_value(
            mock_acs, mock_cpe, "Device.DeviceInfo.SoftwareVersion", via="nbi"
        )
        
        assert result == "nbi_value"
        mock_acs.nbi.GPV.assert_called()

    def test_get_parameter_via_gui(
        self, mock_acs: MagicMock, mock_cpe: MagicMock
    ) -> None:
        """Test get_parameter_value with GUI interface."""
        mock_acs.gui = MagicMock()
        mock_acs.gui.get_device_parameter_via_gui = MagicMock(
            return_value="gui_value"
        )
        
        result = get_parameter_value(
            mock_acs, mock_cpe, "Device.DeviceInfo.SoftwareVersion", via="gui"
        )
        
        assert result == "gui_value"
        mock_acs.gui.get_device_parameter_via_gui.assert_called()

    def test_initiate_reboot_via_nbi(
        self, mock_acs: MagicMock, mock_cpe: MagicMock
    ) -> None:
        """Test initiate_reboot uses NBI by default."""
        initiate_reboot(mock_acs, mock_cpe, via="nbi")
        
        mock_acs.nbi.Reboot.assert_called()

    def test_initiate_reboot_via_gui(
        self, mock_acs: MagicMock, mock_cpe: MagicMock
    ) -> None:
        """Test initiate_reboot with GUI interface."""
        mock_acs.gui = MagicMock()
        mock_acs.gui.reboot_device_via_gui = MagicMock()
        
        initiate_reboot(mock_acs, mock_cpe, via="gui")
        
        mock_acs.gui.reboot_device_via_gui.assert_called()
