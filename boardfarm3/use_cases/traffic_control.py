"""Traffic control use cases.

Provides BDD-friendly wrappers around :class:`~boardfarm3.templates.traffic_controller.TrafficController`
device methods.  Test steps and scenarios depend only on this module — they never call
Linux ``tc`` or hardware appliance APIs directly.

**Device selection:**

- :func:`get_traffic_controller` — returns a single :class:`~boardfarm3.templates.traffic_controller.TrafficController`
  by name (multi-WAN) or automatically when only one is present (single-WAN).

**Symmetric impairment operations** (all interfaces at once):

- :func:`set_impairment_profile` — apply one profile to all interfaces.
- :func:`clear_impairment` — remove all impairments from all interfaces.
- :func:`apply_preset` — resolve a named preset from env config and apply it to all interfaces.

**Per-interface impairment operations** (one interface at a time):

- :func:`set_interface_profile` — apply a profile to a single named interface.
- :func:`get_impairment_profile` — read current profile from one named interface.
- :func:`get_all_impairment_profiles` — read current profiles from all interfaces.

**Transient events (fire-and-forget):**

- :func:`inject_blackout` — 100 % loss for *duration_ms*.
- :func:`inject_brownout` — degraded link for *duration_ms*.
- :func:`inject_latency_spike` — high latency spike for *duration_ms*.
- :func:`inject_packet_storm` — burst packet loss for *duration_ms*.

Preset resolution:

Named presets (e.g. ``"cable_typical"``, ``"satellite"``) are defined in env config under
``environment_def.impairment_presets`` and are looked up by :func:`_get_preset_from_config`.

See: ``docs/Traffic_Management_Components_Architecture.md §9``
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from boardfarm3.exceptions import DeviceNotFound
from boardfarm3.lib.device_manager import get_device_manager
from boardfarm3.lib.traffic_control import ImpairmentProfile, profile_from_dict
from boardfarm3.templates.traffic_controller import TrafficController

if TYPE_CHECKING:
    from boardfarm3.lib.boardfarm_config import BoardfarmConfig


# ---------------------------------------------------------------------------
# Device selection
# ---------------------------------------------------------------------------


def get_traffic_controller(name: str | None = None) -> TrafficController:
    """Return a :class:`~boardfarm3.templates.traffic_controller.TrafficController` device.

    Supports single-WAN (omit *name*) and multi-WAN (specify *name*) topologies.
    ``get_device_manager().get_devices_by_type(TrafficController)`` returns a
    ``dict[str, TrafficController]`` (device name → instance).

    :param name: Device name (e.g. ``"wan1_tc"``).  If ``None`` and exactly one
        TrafficController exists, return it.  If ``None`` and multiple exist,
        raise :exc:`ValueError` asking the caller to specify a name.
    :return: Selected :class:`~boardfarm3.templates.traffic_controller.TrafficController` instance.
    :raises DeviceNotFound: if no TrafficController devices are registered.
    :raises DeviceNotFound: if *name* is specified but does not match any device.
    :raises ValueError: if *name* is ``None`` and more than one TrafficController exists.
    """
    devs = get_device_manager().get_devices_by_type(
        TrafficController,  # type: ignore[type-abstract]
    )
    if not devs:
        raise DeviceNotFound("No TrafficController devices available in device manager")

    if name is not None:
        if name not in devs:
            available = list(devs)
            raise DeviceNotFound(
                f"TrafficController {name!r} not found. Available: {available}"
            )
        return devs[name]

    if len(devs) > 1:
        raise ValueError(
            f"Multiple TrafficController devices found ({list(devs)}). "
            "Specify name= to select one (e.g. get_traffic_controller('wan1_tc'))."
        )
    return next(iter(devs.values()))


# ---------------------------------------------------------------------------
# Preset resolution
# ---------------------------------------------------------------------------


def _get_preset_from_config(config: BoardfarmConfig, preset_name: str) -> dict:
    """Resolve *preset_name* from ``environment_def.impairment_presets`` in env config.

    :param config: Boardfarm config instance (provides env JSON access).
    :param preset_name: Preset name (e.g. ``"cable_typical"``).
    :return: Preset dict with ``latency_ms``, ``jitter_ms``, ``loss_percent``, etc.
    :raises KeyError: if *preset_name* is not defined in ``impairment_presets``.
    """
    presets: dict = (
        config.env_config.get("environment_def", {}).get("impairment_presets", {})
    )
    if preset_name not in presets:
        available = list(presets)
        raise KeyError(
            f"Preset {preset_name!r} not in environment_def.impairment_presets. "
            f"Available: {available}"
        )
    return presets[preset_name]


# ---------------------------------------------------------------------------
# Symmetric impairment operations (all interfaces)
# ---------------------------------------------------------------------------


def apply_preset(
    controller: TrafficController,
    preset_name: str,
    config: BoardfarmConfig,
    duration_ms: int | None = None,
) -> None:
    """Resolve *preset_name* from env config and apply it to ALL interfaces of *controller*.

    If *duration_ms* is provided, applies the preset as a transient via
    :meth:`~boardfarm3.templates.traffic_controller.TrafficController.inject_transient`
    (the profile is auto-restored after the duration).  Otherwise, applies it as a
    sustained profile via :meth:`~boardfarm3.templates.traffic_controller.TrafficController.set_impairment_profile`.

    Preset format matches :class:`~boardfarm3.lib.traffic_control.ImpairmentProfile`
    fields.  Special key ``"event"`` in the preset dict selects the transient event type
    (``"brownout"``, ``"latency_spike"``, ``"packet_storm"``).  Defaults to
    ``"brownout"`` when applying as transient without an ``"event"`` key.

    :param controller: Target TrafficController device.
    :param preset_name: Name from ``impairment_presets`` (e.g. ``"cable_typical"``).
    :param config: Boardfarm config — used to look up the named preset.
    :param duration_ms: If set, apply as a timed transient; else apply as sustained.
    """
    preset = _get_preset_from_config(config, preset_name)

    if duration_ms is not None:
        event = preset.pop("event", "brownout")
        controller.inject_transient(event, duration_ms, **preset)
    else:
        controller.set_impairment_profile(profile_from_dict(preset))


def set_impairment_profile(
    controller: TrafficController,
    profile: ImpairmentProfile | dict,
) -> None:
    """Apply *profile* to ALL interfaces of *controller* (sustained — no auto-restore).

    :param controller: Target TrafficController device.
    :param profile: :class:`~boardfarm3.lib.traffic_control.ImpairmentProfile` or dict.
    """
    controller.set_impairment_profile(profile)


def clear_impairment(controller: TrafficController) -> None:
    """Remove all impairments from ALL interfaces of *controller*.

    :param controller: Target TrafficController device.
    """
    controller.clear()


# ---------------------------------------------------------------------------
# Per-interface impairment operations
# ---------------------------------------------------------------------------


def set_interface_profile(
    controller: TrafficController,
    interface: str,
    profile: ImpairmentProfile | dict,
) -> None:
    """Apply *profile* to a single named interface of *controller* (sustained).

    Use this when you need asymmetric impairment — e.g. different bandwidth caps
    upstream vs. downstream.

    :param controller: Target TrafficController device.
    :param interface: Kernel interface name (e.g. ``"eth-north"``).
    :param profile: :class:`~boardfarm3.lib.traffic_control.ImpairmentProfile` or dict.
    :raises ValueError: if *interface* is not configured for *controller*.
    """
    controller.set_interface_profile(interface, profile)


def get_impairment_profile(
    controller: TrafficController,
    interface: str,
) -> ImpairmentProfile:
    """Read and return the current impairment parameters for *interface* from *controller*.

    Always queries the device / kernel — never returns cached state.

    :param controller: Target TrafficController device.
    :param interface: Kernel interface name (e.g. ``"eth-north"``).
    :return: Current :class:`~boardfarm3.lib.traffic_control.ImpairmentProfile`.
    :raises ValueError: if *interface* is not configured for *controller*.
    """
    return controller.get_interface_profile(interface)


def get_all_impairment_profiles(
    controller: TrafficController,
) -> dict[str, ImpairmentProfile]:
    """Read and return current impairment profiles for ALL interfaces of *controller*.

    Always queries the device / kernel — never returns cached state.

    :param controller: Target TrafficController device.
    :return: ``{interface_name: ImpairmentProfile}`` for every configured interface.
    """
    return controller.get_interface_profiles()


# ---------------------------------------------------------------------------
# Transient event helpers (applied to all interfaces)
# ---------------------------------------------------------------------------


def inject_blackout(controller: TrafficController, duration_ms: int) -> None:
    """Inject a complete link failure (100 % packet loss) for *duration_ms* milliseconds.

    Fire-and-forget: returns immediately; all interfaces are auto-restored after
    *duration_ms*.  Intended for failover / path-steering convergence tests.

    :param controller: Target TrafficController device.
    :param duration_ms: Duration of the blackout in milliseconds.
    """
    controller.inject_transient("blackout", duration_ms)


def inject_brownout(
    controller: TrafficController,
    duration_ms: int,
    latency_ms: int = 200,
    loss_percent: float = 5.0,
) -> None:
    """Inject degraded link conditions for *duration_ms* milliseconds.

    :param controller: Target TrafficController device.
    :param duration_ms: Duration in milliseconds.
    :param latency_ms: One-way delay during brownout (default 200 ms).
    :param loss_percent: Packet loss during brownout (default 5 %).
    """
    controller.inject_transient(
        "brownout",
        duration_ms,
        latency_ms=latency_ms,
        loss_percent=loss_percent,
    )


def inject_latency_spike(
    controller: TrafficController,
    duration_ms: int,
    spike_latency_ms: int = 500,
) -> None:
    """Inject a temporary high-latency spike above the baseline for *duration_ms*.

    :param controller: Target TrafficController device.
    :param duration_ms: Duration in milliseconds.
    :param spike_latency_ms: Latency during the spike (default 500 ms).
    """
    controller.inject_transient(
        "latency_spike",
        duration_ms,
        spike_latency_ms=spike_latency_ms,
    )


def inject_packet_storm(
    controller: TrafficController,
    duration_ms: int,
    loss_percent: float = 10.0,
) -> None:
    """Inject a burst of packet loss above the baseline for *duration_ms*.

    :param controller: Target TrafficController device.
    :param duration_ms: Duration in milliseconds.
    :param loss_percent: Packet loss percentage during the storm (default 10 %).
    """
    controller.inject_transient(
        "packet_storm",
        duration_ms,
        loss_percent=loss_percent,
    )
