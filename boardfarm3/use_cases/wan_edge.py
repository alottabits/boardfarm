"""WAN Edge use cases.

Provides BDD-friendly wrappers around :class:`~boardfarm3.templates.wan_edge.WANEdgeDevice`
template methods.  Test steps and scenarios depend only on this module — they never call
FRR vtysh, vendor REST APIs, or Linux ip-route directly.

**Device selection:**

- :func:`get_wan_edge` — returns a single :class:`~boardfarm3.templates.wan_edge.WANEdgeDevice`
  by name, or automatically when only one is present.

**Path correctness assertions:**

- :func:`assert_active_path` — assert the DUT is forwarding on the expected WAN label.
- :func:`assert_path_steers_on_impairment` — inject a blackout and assert the DUT steers
  to the expected fallback path.
- :func:`assert_policy_steered_path` — apply a PBR policy and verify the resulting path.
- :func:`assert_wan_interface_status` — assert a WAN interface reports the expected state.
- :func:`assert_path_metrics_within_slo` — assert DUT-reported path metrics are within SLO.

**Convergence time measurement:**

- :func:`measure_failover_convergence` — inject a blackout and measure time to path switch.
- :func:`assert_failover_time` — composite: measure convergence and assert it is within SLO.

See: ``docs/WAN_Edge_Appliance_testing.md §3.6`` and ``§3.8``
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from boardfarm3.exceptions import DeviceNotFound
from boardfarm3.lib.device_manager import get_device_manager
from boardfarm3.templates.wan_edge import LinkStatus, PathMetrics, WANEdgeDevice
from boardfarm3.use_cases import traffic_control as tc_use_cases

if TYPE_CHECKING:
    from boardfarm3.templates.traffic_controller import TrafficController


# ---------------------------------------------------------------------------
# Device selection
# ---------------------------------------------------------------------------


def get_wan_edge(name: str | None = None) -> WANEdgeDevice:
    """Return a :class:`~boardfarm3.templates.wan_edge.WANEdgeDevice` device.

    Supports single-DUT (omit *name*) and multi-DUT (specify *name*) topologies.

    :param name: Device name (e.g. ``"sdwan"``).  If ``None`` and exactly one
        WANEdgeDevice exists, return it.  If ``None`` and multiple exist,
        raise :exc:`ValueError` asking the caller to specify a name.
    :return: Selected :class:`~boardfarm3.templates.wan_edge.WANEdgeDevice` instance.
    :raises DeviceNotFound: if no WANEdgeDevice devices are registered.
    :raises DeviceNotFound: if *name* is specified but does not match any device.
    :raises ValueError: if *name* is ``None`` and more than one WANEdgeDevice exists.
    """
    devs = get_device_manager().get_devices_by_type(
        WANEdgeDevice,  # type: ignore[type-abstract]
    )
    if not devs:
        raise DeviceNotFound("No WANEdgeDevice devices available in device manager")

    if name is not None:
        if name not in devs:
            available = list(devs)
            raise DeviceNotFound(
                f"WANEdgeDevice {name!r} not found. Available: {available}"
            )
        return devs[name]

    if len(devs) > 1:
        raise ValueError(
            f"Multiple WANEdgeDevice devices found ({list(devs)}). "
            "Specify name= to select one (e.g. get_wan_edge('sdwan'))."
        )
    return next(iter(devs.values()))


# ---------------------------------------------------------------------------
# Path correctness assertions
# ---------------------------------------------------------------------------


def assert_active_path(
    dut: WANEdgeDevice,
    expected_wan: str,
    flow_dst: str | None = None,
    *,
    label: str = "",
) -> None:
    """Assert the DUT is currently forwarding traffic on the expected WAN interface.

    .. hint:: Implements steps such as:
        - Then traffic should be forwarded on wan1
        - Then the active path should be wan2

    The most direct path assertion — reads the DUT's current forwarding state
    and compares it to the expected logical WAN label.  No impairment is applied;
    the testbed must already be in the desired state before calling this.

    :param dut: WANEdgeDevice under test.
    :param expected_wan: Logical WAN label expected to be active (e.g. ``"wan1"``).
    :param flow_dst: Optional destination IP to select a specific flow path
        (used when the DUT has per-flow or per-application steering).
    :param label: Optional scenario label for clearer assertion messages.
    :raises AssertionError: if the active interface does not match *expected_wan*.
    """
    active = dut.get_active_wan_interface(flow_dst=flow_dst)
    prefix = f"[{label}] " if label else ""
    assert active == expected_wan, (
        f"{prefix}Expected active path {expected_wan!r} but DUT reports {active!r}"
    )


def assert_path_steers_on_impairment(
    dut: WANEdgeDevice,
    impairment_ctrl: TrafficController,
    impaired_wan: str,
    expected_fallback_wan: str,
    duration_ms: int = 10_000,
    poll_interval_ms: int = 50,
    timeout_ms: int = 3_000,
    *,
    label: str = "",
) -> None:
    """Apply blackout impairment to a WAN link and assert the DUT steers to the expected fallback.

    .. hint:: Implements steps such as:
        - When the wan1 link becomes degraded
        - Then traffic should be re-routed to wan2

    Injects a blackout via :func:`~boardfarm3.use_cases.traffic_control.inject_blackout`
    (self-restoring after *duration_ms*).  Polls until the DUT's active path changes to
    *expected_fallback_wan*, then verifies the correct fallback was selected — not just
    that *any* switch occurred.

    Differs from :func:`measure_failover_convergence`, which measures the convergence
    time for SLO assertions.  This function is a correctness assertion: it verifies the
    DUT chose the right path in response to the impairment.

    :param dut: WANEdgeDevice under test.
    :param impairment_ctrl: TrafficController on the impaired WAN link.
    :param impaired_wan: Logical label of the WAN being impaired (e.g. ``"wan1"``).
    :param expected_fallback_wan: Logical label the DUT should steer to (e.g. ``"wan2"``).
    :param duration_ms: How long the blackout lasts before auto-restore (ms).
    :param poll_interval_ms: Polling interval while waiting for DUT to switch (ms).
    :param timeout_ms: Maximum wait for path switch before failing (ms).
    :param label: Optional scenario label for clearer assertion messages.
    :raises AssertionError: if DUT does not switch to *expected_fallback_wan* within
        *timeout_ms*, or if it switches to an unexpected path.
    """
    prefix = f"[{label}] " if label else ""
    tc_use_cases.inject_blackout(impairment_ctrl, duration_ms=duration_ms)
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        active = dut.get_active_wan_interface()
        if active != impaired_wan:
            assert active == expected_fallback_wan, (
                f"{prefix}DUT steered away from {impaired_wan!r} but chose "
                f"{active!r} instead of expected fallback {expected_fallback_wan!r}"
            )
            return
        time.sleep(poll_interval_ms / 1000)
    raise AssertionError(
        f"{prefix}DUT did not steer away from impaired {impaired_wan!r} "
        f"to {expected_fallback_wan!r} within {timeout_ms}ms"
    )


def assert_policy_steered_path(
    dut: WANEdgeDevice,
    policy: dict,
    flow_dst: str,
    expected_wan: str,
    *,
    label: str = "",
) -> None:
    """Apply a PBR policy and assert the DUT routes the specified flow via the expected WAN.

    .. hint:: Implements steps such as:
        - When a policy routes video traffic via wan2
        - Then traffic to 172.16.0.11 should use wan2

    Calls :meth:`~boardfarm3.templates.wan_edge.WANEdgeDevice.apply_policy` (a
    WANEdgeDevice template method) and then verifies the resulting forwarding decision
    for a specific destination.  The policy dict is vendor-neutral; the device class
    translates it to FRR route-maps, NETCONF RPCs, or REST API calls.

    :param dut: WANEdgeDevice under test.
    :param policy: Vendor-neutral policy dict. Example::

        {
            "match":  {"dscp": 34},           # AF41 — video
            "action": {"prefer_wan": "wan2"}
        }

    :param flow_dst: Destination IP to verify the policy applies to (passed to
        ``get_active_wan_interface`` as *flow_dst*).
    :param expected_wan: Logical WAN label the policy should steer this flow to.
    :param label: Optional scenario label for clearer assertion messages.
    :raises AssertionError: if ``get_active_wan_interface(flow_dst)`` ≠ *expected_wan*
        after the policy is applied.
    """
    prefix = f"[{label}] " if label else ""
    dut.apply_policy(policy)
    active = dut.get_active_wan_interface(flow_dst=flow_dst)
    assert active == expected_wan, (
        f"{prefix}Policy {policy} should steer {flow_dst!r} to {expected_wan!r} "
        f"but DUT reports active path {active!r}"
    )


def assert_wan_interface_status(
    dut: WANEdgeDevice,
    wan_label: str,
    expected_state: str,
    *,
    label: str = "",
) -> LinkStatus:
    """Assert a specific WAN interface is in the expected operational state.

    .. hint:: Implements steps such as:
        - Then wan1 should be up
        - Then wan2 should report a degraded state
        - Then the failed link should be down

    Reads the DUT's interface status table and asserts the named WAN link
    reports the expected state.  Used to verify interface recovery after
    impairment is cleared, or to confirm a deliberate admin-down state before
    a failover test.

    :param dut: WANEdgeDevice under test.
    :param wan_label: Logical WAN label to check (e.g. ``"wan1"``).
    :param expected_state: Expected state string: ``"up"`` | ``"down"`` | ``"degraded"``.
    :param label: Optional scenario label for clearer assertion messages.
    :return: The full :class:`~boardfarm3.templates.wan_edge.LinkStatus` for further
        inspection if needed.
    :raises KeyError: if *wan_label* is not present in the status dict.
    :raises AssertionError: if the interface state does not match *expected_state*.
    """
    prefix = f"[{label}] " if label else ""
    statuses = dut.get_wan_interface_status()
    assert wan_label in statuses, (
        f"{prefix}WAN label {wan_label!r} not found in DUT interface status. "
        f"Available: {list(statuses.keys())}"
    )
    status = statuses[wan_label]
    assert status.state == expected_state, (
        f"{prefix}WAN interface {wan_label!r} expected state {expected_state!r} "
        f"but reports {status.state!r} (IP: {status.ip_address})"
    )
    return status


def assert_path_metrics_within_slo(
    dut: WANEdgeDevice,
    wan_label: str,
    max_latency_ms: float | None = None,
    max_jitter_ms: float | None = None,
    max_loss_percent: float | None = None,
    *,
    label: str = "",
) -> PathMetrics:
    """Assert the DUT's measured path metrics for a WAN link are within defined thresholds.

    .. hint:: Implements steps such as:
        - Then the wan1 latency should be below 50ms
        - Then the wan2 packet loss should be below 1%

    Uses :meth:`~boardfarm3.templates.wan_edge.WANEdgeDevice.get_wan_path_metrics` —
    on the Linux Router this is implemented via active ping probes; on commercial DUTs
    via built-in SLA monitoring.  The same assertion code works for both because the
    template normalises the result to :class:`~boardfarm3.templates.wan_edge.PathMetrics`.

    :param dut: WANEdgeDevice under test.
    :param wan_label: Logical WAN label to check (e.g. ``"wan1"``).
    :param max_latency_ms: Maximum acceptable one-way latency in ms. ``None`` = skip check.
    :param max_jitter_ms: Maximum acceptable jitter in ms. ``None`` = skip check.
    :param max_loss_percent: Maximum acceptable packet loss (0–100). ``None`` = skip check.
    :param label: Optional scenario label for clearer assertion messages.
    :return: The full :class:`~boardfarm3.templates.wan_edge.PathMetrics` for the link.
    :raises AssertionError: if any provided threshold is exceeded, or if *wan_label* is
        not found in the metrics dict.
    """
    prefix = f"[{label}] " if label else ""
    all_metrics = dut.get_wan_path_metrics()
    assert wan_label in all_metrics, (
        f"{prefix}WAN label {wan_label!r} not found in path metrics. "
        f"Available: {list(all_metrics.keys())}"
    )
    m = all_metrics[wan_label]
    if max_latency_ms is not None:
        assert m.latency_ms <= max_latency_ms, (
            f"{prefix}{wan_label} latency {m.latency_ms:.1f}ms exceeds SLO {max_latency_ms}ms"
        )
    if max_jitter_ms is not None:
        assert m.jitter_ms <= max_jitter_ms, (
            f"{prefix}{wan_label} jitter {m.jitter_ms:.1f}ms exceeds SLO {max_jitter_ms}ms"
        )
    if max_loss_percent is not None:
        assert m.loss_percent <= max_loss_percent, (
            f"{prefix}{wan_label} packet loss {m.loss_percent:.2f}% exceeds SLO {max_loss_percent}%"
        )
    return m


# ---------------------------------------------------------------------------
# Path-switch polling (no injection — for use between BDD steps)
# ---------------------------------------------------------------------------


def wait_for_path_switch(
    dut: WANEdgeDevice,
    expected_wan: str,
    timeout_ms: int = 5_000,
    poll_interval_ms: int = 50,
    *,
    label: str = "",
) -> float:
    """Poll until the DUT's active forwarding path matches *expected_wan*.

    Unlike :func:`measure_failover_convergence`, this function does **not**
    inject any impairment — it only polls.  Use it when the impairment (or
    recovery) has already been applied in a prior BDD step and you need to
    wait for the DUT to react.

    .. hint:: Implements steps such as:

        - Then the appliance converges to wan2 within 1000 ms
        - Then the appliance fails back to wan1 as the preferred path
        - Then the appliance steers traffic to wan2

    :param dut: WANEdgeDevice under test.
    :param expected_wan: Logical WAN label to wait for (e.g. ``"wan2"``).
    :param timeout_ms: Maximum wait before raising (ms).
    :param poll_interval_ms: Polling interval (ms).
    :param label: Optional scenario label for assertion messages.
    :return: Elapsed time in milliseconds until the path matched.
    :raises AssertionError: if the path does not match within *timeout_ms*.
    """
    prefix = f"[{label}] " if label else ""
    t0 = time.monotonic()
    deadline = t0 + timeout_ms / 1000
    while time.monotonic() < deadline:
        if dut.get_active_wan_interface() == expected_wan:
            return (time.monotonic() - t0) * 1000
        time.sleep(poll_interval_ms / 1000)
    active = dut.get_active_wan_interface()
    raise AssertionError(
        f"{prefix}DUT did not switch to {expected_wan!r} within {timeout_ms}ms "
        f"(current active: {active!r})"
    )


# ---------------------------------------------------------------------------
# Convergence time measurement
# ---------------------------------------------------------------------------


def measure_failover_convergence(
    dut: WANEdgeDevice,
    impairment_ctrl: TrafficController,
    primary_link: str,
    backup_link: str,
    poll_interval_ms: int = 50,
    timeout_ms: int = 5_000,
) -> float:
    """Inject a blackout on *primary_link* and measure time until DUT switches to *backup_link*.

    .. hint:: Implements steps such as:
        - Then the DUT should switch to the backup path within 1000ms

    Injects a blackout (self-restoring after *timeout_ms* + 1 s) and polls
    :meth:`~boardfarm3.templates.wan_edge.WANEdgeDevice.get_active_wan_interface`
    until the DUT reports *backup_link* as active.

    :param dut: WANEdgeDevice instance.
    :param impairment_ctrl: TrafficController for the primary WAN link.
    :param primary_link: Expected primary WAN label (e.g. ``"wan1"``).
    :param backup_link: Expected backup WAN label (e.g. ``"wan2"``).
    :param poll_interval_ms: How often to poll the DUT's active interface (ms).
    :param timeout_ms: Maximum wait for convergence before raising (ms).
    :return: Convergence time in milliseconds.
    :raises AssertionError: if convergence does not occur within *timeout_ms*.
    """
    tc_use_cases.inject_blackout(impairment_ctrl, duration_ms=timeout_ms + 1_000)
    t0 = time.monotonic()
    deadline = t0 + timeout_ms / 1000
    while time.monotonic() < deadline:
        if dut.get_active_wan_interface() == backup_link:
            return (time.monotonic() - t0) * 1000
        time.sleep(poll_interval_ms / 1000)
    raise AssertionError(
        f"DUT did not switch from {primary_link!r} to {backup_link!r} "
        f"within {timeout_ms}ms"
    )


def assert_failover_time(
    dut: WANEdgeDevice,
    impairment_ctrl: TrafficController,
    primary_link: str,
    backup_link: str,
    max_ms: float,
    *,
    label: str = "",
) -> float:
    """Measure failover convergence and assert it is within the SLO threshold.

    .. hint:: Implements steps such as:
        - Then the DUT should switch to the backup path within 1000ms

    Composite function: calls :func:`measure_failover_convergence` and then
    asserts the result is at or below *max_ms*.

    :param dut: WANEdgeDevice instance.
    :param impairment_ctrl: TrafficController for the primary WAN link.
    :param primary_link: Expected primary WAN label (e.g. ``"wan1"``).
    :param backup_link: Expected backup WAN label (e.g. ``"wan2"``).
    :param max_ms: Maximum acceptable convergence time in milliseconds.
    :param label: Optional scenario label for clearer assertion messages.
    :return: Actual convergence time in milliseconds.
    :raises AssertionError: if convergence time exceeds *max_ms*.
    """
    prefix = f"[{label}] " if label else ""
    conv_ms = measure_failover_convergence(
        dut, impairment_ctrl, primary_link, backup_link
    )
    assert conv_ms <= max_ms, (
        f"{prefix}Failover convergence {conv_ms:.0f}ms exceeded SLO {max_ms:.0f}ms"
    )
    return conv_ms
