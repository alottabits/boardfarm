"""Traffic generator use cases.

Provides BDD-friendly wrappers around
:class:`~boardfarm3.templates.traffic_generator.TrafficGenerator` device methods.
Test steps and scenarios depend only on this module -- they never call iPerf3 or
hardware appliance APIs directly.

**Device selection:**

- :func:`get_traffic_generator` -- returns a single
  :class:`~boardfarm3.templates.traffic_generator.TrafficGenerator` by name (multi-site)
  or automatically when only one is present.

**Core flow operations** (thin wrappers):

- :func:`start_traffic` -- non-blocking, returns ``flow_id``.
- :func:`stop_traffic` -- stop one flow, return its result.
- :func:`stop_all_traffic` -- stop all flows on a single generator.
- :func:`run_traffic` -- blocking single-flow convenience.

**Convenience helpers** (enabled by multi-flow + dual-instance design):

- :func:`saturate_wan_link` -- start a background flow sized to saturate a WAN link.
- :func:`start_asymmetric_load` -- start flows in both directions simultaneously.
- :func:`stop_all_generators` -- bulk teardown across multiple generators.

See: ``docs/examples/sdwan-digital-twin/future/traffic-generator.md``
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from boardfarm3.exceptions import DeviceNotFound
from boardfarm3.lib.device_manager import get_device_manager
from boardfarm3.templates.traffic_generator import (
    TrafficGenerator,
    TrafficResult,
    TrafficSpec,
)

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Device selection
# ---------------------------------------------------------------------------


def get_traffic_generator(name: str | None = None) -> TrafficGenerator:
    """Return a :class:`~boardfarm3.templates.traffic_generator.TrafficGenerator` device.

    .. hint:: This Use Case implements statements from the test suite such as:

        - the traffic generators are available on both sides of the appliance
        - the LAN-side traffic generator is available

    :param name: Device name (e.g. ``"lan_traffic_gen"``).  If ``None`` and exactly
        one TrafficGenerator exists, return it.  If ``None`` and multiple exist,
        raise :exc:`ValueError`.
    :return: Selected :class:`~boardfarm3.templates.traffic_generator.TrafficGenerator`.
    :raises DeviceNotFound: if no TrafficGenerator devices are registered.
    :raises DeviceNotFound: if *name* does not match any device.
    :raises ValueError: if *name* is ``None`` and more than one exists.
    """
    devs = get_device_manager().get_devices_by_type(
        TrafficGenerator,  # type: ignore[type-abstract]
    )
    if not devs:
        raise DeviceNotFound("No TrafficGenerator devices available in device manager")

    if name is not None:
        if name not in devs:
            available = list(devs)
            raise DeviceNotFound(
                f"TrafficGenerator {name!r} not found. Available: {available}"
            )
        return devs[name]

    if len(devs) > 1:
        raise ValueError(
            f"Multiple TrafficGenerator devices found ({list(devs)}). "
            "Specify name= to select one (e.g. get_traffic_generator('lan_traffic_gen'))."
        )
    return next(iter(devs.values()))


# ---------------------------------------------------------------------------
# Core flow operations (thin wrappers)
# ---------------------------------------------------------------------------


def start_traffic(generator: TrafficGenerator, spec: TrafficSpec) -> str:
    """Start a background traffic flow on *generator*.  Non-blocking.

    .. hint:: This Use Case implements statements from the test suite such as:

        - 85 Mbps of "BE" upstream background load is started through the appliance
        - 85 Mbps of "BE" downstream background load is started through the appliance

    :param generator: Target TrafficGenerator device.
    :param spec: Traffic parameters (rate, protocol, DSCP, destination).
    :return: Opaque flow identifier for use with :func:`stop_traffic`.
    """
    return generator.start_traffic(spec)


def stop_traffic(generator: TrafficGenerator, flow_id: str) -> TrafficResult:
    """Stop a specific flow on *generator* and return its results.

    .. hint:: This Use Case implements statements from the test suite such as:

        - the upstream background load is stopped and results collected
        - the downstream background load is stopped and results collected

    :param generator: Target TrafficGenerator device.
    :param flow_id: Identifier returned by :func:`start_traffic`.
    :return: :class:`TrafficResult` with achieved rates and loss statistics.
    """
    return generator.stop_traffic(flow_id)


def stop_all_traffic(generator: TrafficGenerator) -> dict[str, TrafficResult]:
    """Stop ALL active flows on *generator* and return results for each.

    .. hint:: This Use Case implements statements from the test suite such as:

        - all background load is stopped and results collected

    :param generator: Target TrafficGenerator device.
    :return: ``{flow_id: TrafficResult}`` for every flow that was active.
    """
    return generator.stop_all_traffic()


def run_traffic(generator: TrafficGenerator, spec: TrafficSpec) -> TrafficResult:
    """Run a single traffic flow to completion on *generator*.  Blocking.

    :param generator: Target TrafficGenerator device.
    :param spec: Traffic parameters.
    :return: :class:`TrafficResult` with achieved rates and loss statistics.
    """
    return generator.run_traffic(spec)


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


def saturate_wan_link(
    source: TrafficGenerator,
    destination: TrafficGenerator,
    link_bandwidth_mbps: float,
    dscp: int = 0,
    utilisation_pct: float = 0.85,
    duration_s: int = 120,
) -> str:
    """Start a background flow sized to saturate a WAN link.

    .. hint:: This Use Case implements statements from the test suite such as:

        - 85 Mbps of "BE" upstream background load is started through the appliance
        - the WAN link is saturated with best-effort traffic

    :param source: Generator that will send traffic.
    :param destination: Generator whose :attr:`server_ip` is targeted.
    :param link_bandwidth_mbps: Nominal link bandwidth in Mbps.
    :param dscp: DSCP code point for the background traffic (default 0 = BE).
    :param utilisation_pct: Fraction of link bandwidth to use (default 0.85 = 85%).
    :param duration_s: Flow duration in seconds (default 120).
    :return: Flow identifier.
    """
    spec = TrafficSpec(
        destination=destination.server_ip,
        bandwidth_mbps=link_bandwidth_mbps * utilisation_pct,
        protocol="udp",
        dscp=dscp,
        duration_s=duration_s,
    )
    return source.start_traffic(spec)


def start_asymmetric_load(
    upstream_gen: TrafficGenerator,
    downstream_gen: TrafficGenerator,
    upstream_spec: TrafficSpec,
    downstream_spec: TrafficSpec,
) -> tuple[str, str]:
    """Start flows in both directions simultaneously.

    .. hint:: This Use Case implements statements from the test suite such as:

        - asymmetric background load is started with 80 Mbps upstream and 40 Mbps downstream

    :param upstream_gen: Generator on the LAN side (sends upstream).
    :param downstream_gen: Generator on the north side (sends downstream).
    :param upstream_spec: Spec for the upstream flow (destination should be
        ``downstream_gen.server_ip``).
    :param downstream_spec: Spec for the downstream flow (destination should be
        ``upstream_gen.server_ip``).
    :return: ``(upstream_flow_id, downstream_flow_id)``.
    """
    up_fid = upstream_gen.start_traffic(upstream_spec)
    down_fid = downstream_gen.start_traffic(downstream_spec)
    return up_fid, down_fid


def stop_all_generators(
    *generators: TrafficGenerator,
) -> dict[str, dict[str, TrafficResult]]:
    """Stop all flows on multiple generators.  For bulk teardown in fixtures.

    :param generators: One or more TrafficGenerator devices.
    :return: ``{device_name: {flow_id: TrafficResult}}`` for every generator that
        had active flows.  Generators with no active flows are omitted.
    """
    results: dict[str, dict[str, TrafficResult]] = {}
    for gen in generators:
        if gen.active_flows:
            gen_results = gen.stop_all_traffic()
            if gen_results:
                results[getattr(gen, "device_name", str(gen))] = gen_results
    return results
