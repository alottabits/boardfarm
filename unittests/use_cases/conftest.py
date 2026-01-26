"""Shared fixtures for use_cases unit tests."""

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, PropertyMock

import pytest


@pytest.fixture
def mock_acs() -> MagicMock:
    """Create a mock ACS device."""
    acs = MagicMock()
    
    # Mock console for log access
    acs.console = MagicMock()
    acs.console.execute_command = MagicMock(return_value="")
    
    # Mock NBI interface
    acs.nbi = MagicMock()
    acs.nbi.GPV = MagicMock(return_value=[{"value": "test_value"}])
    acs.nbi.SPV = MagicMock(return_value=0)
    acs.nbi.Reboot = MagicMock()
    acs.nbi.connection_request = MagicMock(return_value=True)
    
    # Mock legacy methods that delegate to nbi
    acs.GPV = MagicMock(return_value=[{"value": "test_value"}])
    acs.SPV = MagicMock(return_value=0)
    acs.Reboot = MagicMock()
    
    return acs


@pytest.fixture
def mock_cpe() -> MagicMock:
    """Create a mock CPE device."""
    cpe = MagicMock()
    
    # Mock sw interface
    cpe.sw = MagicMock()
    cpe.sw.cpe_id = "TEST-CPE-001"
    cpe.sw.get_seconds_uptime = MagicMock(return_value=3600)
    
    # Mock hw interface
    cpe.hw = MagicMock()
    mock_console = MagicMock()
    mock_console.execute_command = MagicMock(return_value="3600.00 1000.00")
    cpe.hw.get_console = MagicMock(return_value=mock_console)
    cpe.hw.connect_to_consoles = MagicMock()
    cpe.hw.disconnect_from_consoles = MagicMock()
    
    # Mock device_name attribute
    cpe.device_name = "cpe"
    
    return cpe


@pytest.fixture
def mock_sip_phone() -> MagicMock:
    """Create a mock SIP phone device."""
    phone = MagicMock()
    phone.name = "test_phone"
    phone.number = "1001"
    phone.dial = MagicMock()
    phone.answer = MagicMock()
    phone.hangup = MagicMock()
    phone.on_hook = MagicMock()
    phone.off_hook = MagicMock()
    phone.is_idle = MagicMock(return_value=True)
    phone.is_ringing = MagicMock(return_value=False)
    phone.is_connected = MagicMock(return_value=False)
    return phone


@pytest.fixture
def sample_log_lines() -> list[str]:
    """Sample GenieACS log lines for testing."""
    return [
        '2024-01-15T10:30:00.123Z [INFO] ::ffff:172.25.1.1 TEST-CPE-001: Inform',
        '2024-01-15T10:30:01.456Z [INFO] ::ffff:172.25.1.1 TEST-CPE-001: '
        'ACS request; acsRequestName="Reboot"',
        '2024-01-15T10:30:02.789Z [INFO] ::ffff:172.25.1.1 TEST-CPE-001: '
        'Inform; eventCodes="1 BOOT,M Reboot"',
        '2024-01-15T10:30:03.000Z [INFO] ::ffff:172.25.1.2 OTHER-CPE-002: Inform',
    ]


@pytest.fixture
def test_timestamp() -> datetime:
    """Test timestamp for filtering."""
    return datetime(2024, 1, 15, 10, 29, 59)
