"""Use cases to interact with devices.

This module provides high-level test operations that serve as the single
source of truth for test automation. These use cases are designed to be
portable across different test frameworks (pytest-bdd, Robot Framework).

Available Modules:
    - acs: ACS/TR-069 operations (get/set parameters, reboot, log monitoring)
    - cpe: CPE device operations (uptime, factory reset, TR-069 client control)
    - networking: Network operations (ping, HTTP, DNS, TCP/UDP)
    - voice: SIP/Voice operations (call setup, answer, disconnect)
    - wifi: WiFi operations (SSID, client connections)
    - dhcp: DHCP operations (release, renew)
    - iperf: Performance testing (iperf client/server)
"""
