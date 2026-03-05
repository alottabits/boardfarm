"""Boardfarm Linux Traffic Controller device module.

Implements :class:`~boardfarm3.templates.traffic_controller.TrafficController` using
Linux ``tc netem`` (iproute2).  Designed for dedicated, multi-homed impairment containers
in the SD-WAN testbed (``wan1-tc``, ``wan2-tc``) but works with any number of interfaces.

**tc netem principle:**

``tc netem`` operates on egress only.  A Traffic Controller container with two interfaces
connected to opposite sides of a WAN link applies impairment to traffic as it leaves each
interface.  This gives full asymmetric control without IFB (Intermediate Functional Block).

**Multi-interface design:**

Interfaces are declared as a dict in the environment config.  Each entry maps a kernel
interface name to its initial :class:`~boardfarm3.lib.traffic_control.ImpairmentProfile`.
Asymmetry between directions is expressed by assigning different profiles to different
interfaces — there are no direction-specific fields within a single profile::

    "wan1_tc": {
      "interfaces": {
        "eth-north": {"latency_ms": 5, "jitter_ms": 1, "loss_percent": 0, "bandwidth_limit_mbps": 1000},
        "eth-dut":   {"latency_ms": 5, "jitter_ms": 1, "loss_percent": 0, "bandwidth_limit_mbps": 1000}
      }
    }

**Design notes:**

- ``get_interface_profile`` / ``get_interface_profiles`` always read from ``tc -j qdisc show``
  (kernel state); they never return cached in-memory state.  See §7.1 of
  ``docs/Traffic_Management_Components_Architecture.md`` for the rationale.
- :meth:`inject_transient` is fire-and-forget.  A daemon thread restores each interface
  to its pre-injection kernel state after ``duration_ms``.  Concurrent calls to
  :meth:`set_impairment_profile`, :meth:`set_interface_profile`, :meth:`clear`, or a new
  :meth:`inject_transient` cancel the pending restore before proceeding.

See: ``docs/Traffic_Management_Components_Architecture.md``
"""

from __future__ import annotations

import logging
import threading
from argparse import Namespace
from typing import TYPE_CHECKING

from boardfarm3 import hookimpl
from boardfarm3.devices.base_devices.linux_device import LinuxDevice
from boardfarm3.lib.traffic_control import (
    ImpairmentProfile,
    _build_transient_profile,
    apply_tc_profile,
    clear_tc_profile,
    profile_from_dict,
    read_tc_profile,
)
from boardfarm3.templates.traffic_controller import TrafficController

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)


class LinuxTrafficController(LinuxDevice, TrafficController):
    """Boardfarm Linux Traffic Controller device.

    Standalone SSH container running Linux ``tc netem`` for WAN impairment.
    Manages a configurable set of kernel interfaces; each interface can carry an
    independent :class:`~boardfarm3.lib.traffic_control.ImpairmentProfile`.

    Uses :class:`~boardfarm3.devices.base_devices.linux_device.LinuxDevice` SSH
    connection (``connection_type: authenticated_ssh``).  Inventory keys:
    ``ipaddr``, ``port``, ``username`` (default ``root``), ``password`` (default
    ``boardfarm``).  Interface names and initial profiles come from the merged env
    config (``environment_def[device_name].interfaces``).
    """

    def __init__(self, config: dict, cmdline_args: Namespace) -> None:
        """Initialize Linux Traffic Controller.

        Reads the ``interfaces`` dict from *config* (merged from env JSON).
        Does **not** apply the default profiles here — profiles are applied in
        :meth:`boardfarm_skip_boot` / :meth:`boardfarm_device_boot` after the SSH
        connection is established.

        :param config: Merged device config (inventory + env_def).  Must include an
            ``interfaces`` dict mapping interface names to profile dicts.
        :param cmdline_args: Boardfarm CLI arguments.
        :raises KeyError: if ``interfaces`` is absent or empty in *config*.
        """
        super().__init__(config, cmdline_args)

        interfaces_config: dict = config.get("interfaces", {})
        if not interfaces_config:
            raise KeyError(
                f"Device {self.device_name!r} ({self.device_type!r}): "
                "'interfaces' is required and must be non-empty. "
                "Define it in environment_def[device_name] in the boardfarm env JSON, "
                "e.g.: \"interfaces\": {\"eth-north\": {...}, \"eth-dut\": {...}}"
            )

        self._interfaces: list[str] = list(interfaces_config.keys())
        self._interfaces_config: dict[str, dict] = interfaces_config

        # Background thread cancel event for inject_transient auto-restore
        self._restore_cancel: threading.Event | None = None

    # ------------------------------------------------------------------
    # TrafficController interface — symmetric operations (all interfaces)
    # ------------------------------------------------------------------

    def set_impairment_profile(self, profile: ImpairmentProfile | dict) -> None:
        """Apply *profile* to ALL configured interfaces (sustained — no auto-restore).

        Cancels any pending auto-restore scheduled by :meth:`inject_transient`.

        :param profile: :class:`~boardfarm3.lib.traffic_control.ImpairmentProfile`
            or plain dict.  Dict is auto-converted via
            :func:`~boardfarm3.lib.traffic_control.profile_from_dict`.
        """
        self._cancel_restore()
        p = profile_from_dict(profile) if isinstance(profile, dict) else profile
        for iface in self._interfaces:
            apply_tc_profile(self._console, iface, p)

    def clear(self) -> None:
        """Remove all tc qdiscs from ALL configured interfaces (return to kernel default).

        Cancels any pending auto-restore scheduled by :meth:`inject_transient`.
        """
        self._cancel_restore()
        for iface in self._interfaces:
            clear_tc_profile(self._console, iface)

    def inject_transient(
        self,
        event: str,
        duration_ms: int,
        **kwargs: float | int,
    ) -> None:
        """Inject a timed transient impairment event on ALL interfaces; returns immediately.

        Reads the current per-interface kernel state, applies the transient profile to all
        interfaces, and starts a daemon thread that restores each interface to its
        pre-injection profile after *duration_ms*.

        The transient is built using the first configured interface's current profile as the
        baseline (symmetric testbeds have the same profile on all interfaces, so this is
        always correct; for asymmetric testbeds, the first-interface baseline governs the
        transient shape while restore still returns each interface to its own profile).

        A concurrent call to :meth:`set_impairment_profile`, :meth:`set_interface_profile`,
        :meth:`clear`, or another :meth:`inject_transient` cancels the pending restore
        before proceeding.

        :param event: ``"blackout"``, ``"brownout"``, ``"latency_spike"``, or
            ``"packet_storm"``.
        :param duration_ms: Transient duration in milliseconds.
        :param kwargs: Event-specific overrides (e.g. ``spike_latency_ms=500``).
        """
        self._cancel_restore()

        # Read current state for ALL interfaces before applying transient
        previous: dict[str, ImpairmentProfile] = self.get_interface_profiles()

        # Build transient using first interface's profile as the reference baseline
        baseline = previous[self._interfaces[0]]
        transient = _build_transient_profile(event, baseline, **kwargs)

        # Apply transient to ALL interfaces
        for iface in self._interfaces:
            apply_tc_profile(self._console, iface, transient)

        cancel_event = threading.Event()
        self._restore_cancel = cancel_event

        def _restore() -> None:
            cancelled = cancel_event.wait(timeout=duration_ms / 1000.0)
            if not cancelled:
                for iface, prof in previous.items():
                    apply_tc_profile(self._console, iface, prof)

        threading.Thread(
            target=_restore, daemon=True, name=f"tc-restore-{self.device_name}"
        ).start()

    # ------------------------------------------------------------------
    # TrafficController interface — per-interface operations
    # ------------------------------------------------------------------

    def set_interface_profile(
        self, interface: str, profile: ImpairmentProfile | dict
    ) -> None:
        """Apply *profile* to a single named interface (sustained — no auto-restore).

        Cancels any pending auto-restore scheduled by :meth:`inject_transient`.

        :param interface: Kernel interface name.  Must be one of the configured interfaces.
        :param profile: :class:`~boardfarm3.lib.traffic_control.ImpairmentProfile`
            or plain dict (auto-converted).
        :raises ValueError: if *interface* is not in the configured interface set.
        """
        self._validate_interface(interface)
        self._cancel_restore()
        p = profile_from_dict(profile) if isinstance(profile, dict) else profile
        apply_tc_profile(self._console, interface, p)

    def get_interface_profile(self, interface: str) -> ImpairmentProfile:
        """Return the current impairment profile for *interface* from the kernel.

        Reads ``tc -j qdisc show dev <interface>`` — never returns cached state.

        :param interface: Kernel interface name.  Must be one of the configured interfaces.
        :return: Current :class:`~boardfarm3.lib.traffic_control.ImpairmentProfile`.
        :raises ValueError: if *interface* is not in the configured interface set.
        """
        self._validate_interface(interface)
        return read_tc_profile(self._console, interface)

    def get_interface_profiles(self) -> dict[str, ImpairmentProfile]:
        """Return current impairment profiles for ALL configured interfaces.

        Reads ``tc -j qdisc show dev <iface>`` for each interface — never cached.

        :return: ``{interface_name: ImpairmentProfile}`` for every configured interface.
        """
        return {iface: read_tc_profile(self._console, iface) for iface in self._interfaces}

    # ------------------------------------------------------------------
    # Boardfarm hooks
    # ------------------------------------------------------------------

    @hookimpl
    def boardfarm_skip_boot(self) -> None:
        """Connect and apply default impairment profiles (skip-boot path)."""
        _LOGGER.info("Initializing %s (%s)", self.device_name, self.device_type)
        self._connect()
        self._apply_default_profiles()

    @hookimpl
    async def boardfarm_skip_boot_async(self) -> None:
        """Connect and apply default impairment profiles — async variant."""
        _LOGGER.info("Initializing %s (%s)", self.device_name, self.device_type)
        await self._connect_async()
        self._apply_default_profiles()

    @hookimpl
    def boardfarm_device_boot(self, device_manager: object) -> None:  # pylint: disable=unused-argument
        """Connect and apply default impairment profiles (full-boot path)."""
        _LOGGER.info("Booting %s (%s)", self.device_name, self.device_type)
        self._connect()
        self._apply_default_profiles()

    @hookimpl
    async def boardfarm_device_boot_async(self, device_manager: object) -> None:  # pylint: disable=unused-argument
        """Connect and apply default impairment profiles — async variant."""
        _LOGGER.info("Booting %s (%s)", self.device_name, self.device_type)
        await self._connect_async()
        self._apply_default_profiles()

    @hookimpl
    def boardfarm_shutdown_device(self) -> None:
        """Cancel pending restore and disconnect."""
        _LOGGER.info("Shutdown %s (%s)", self.device_name, self.device_type)
        self._cancel_restore()
        self._disconnect()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _validate_interface(self, interface: str) -> None:
        """Raise :exc:`ValueError` if *interface* is not in the configured set."""
        if interface not in self._interfaces:
            raise ValueError(
                f"Interface {interface!r} is not configured for {self.device_name!r}. "
                f"Configured interfaces: {self._interfaces}"
            )

    def _cancel_restore(self) -> None:
        """Signal any pending restore thread to abort without restoring."""
        if self._restore_cancel is not None:
            self._restore_cancel.set()
            self._restore_cancel = None

    def _apply_default_profiles(self) -> None:
        """Apply per-interface initial profiles from ``interfaces`` env config."""
        for iface in self._interfaces:
            profile_data = self._interfaces_config.get(iface)
            if profile_data:
                _LOGGER.info(
                    "Applying default profile for %s[%s]: %s",
                    self.device_name,
                    iface,
                    profile_data,
                )
                apply_tc_profile(self._console, iface, profile_from_dict(profile_data))
            else:
                _LOGGER.debug(
                    "No default profile configured for %s[%s]", self.device_name, iface
                )
