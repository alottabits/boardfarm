"""Boardfarm TrafficController device template."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from boardfarm3.lib.traffic_control import ImpairmentProfile


class TrafficController(ABC):
    """Abstract interface for network impairment / traffic control implementations.

    Impairment parameters are expressed as :class:`~boardfarm3.lib.traffic_control.ImpairmentProfile`
    objects (or plain dicts, which are auto-converted). Use cases depend only on this
    interface — implementations (Linux tc, Spirent) are interchangeable.

    **Multi-interface design:**

    A TrafficController manages a set of named network interfaces (e.g. ``"eth-north"``,
    ``"eth-dut"``). Each interface has its own independent
    :class:`~boardfarm3.lib.traffic_control.ImpairmentProfile`.  Asymmetry between
    directions is expressed by applying *different* profiles to *different* interfaces —
    not by direction-specific fields within a single profile.

    **Symmetric operations** (all interfaces at once):
    - :meth:`set_impairment_profile` — apply one profile to ALL interfaces.
    - :meth:`clear` — remove all qdiscs from ALL interfaces.
    - :meth:`inject_transient` — apply a timed event to ALL interfaces; auto-restores.

    **Per-interface operations** (one interface at a time):
    - :meth:`set_interface_profile` — apply a profile to one named interface.
    - :meth:`get_interface_profile` — read current profile from one named interface.
    - :meth:`get_interface_profiles` — read current profiles from all interfaces.

    **Design notes:**
    - ``get_interface_profile`` / ``get_interface_profiles`` always read from the device /
      kernel.  They never return cached in-memory state.  This mirrors how a hardware
      appliance exposes its current configuration via a REST API poll.
    - :meth:`inject_transient` is fire-and-forget: it returns immediately and
      auto-restores all interfaces to their previous profiles after ``duration_ms``.
    - :meth:`set_impairment_profile`, :meth:`set_interface_profile`, and :meth:`clear`
      cancel any pending auto-restore before applying the new profile.
    """

    @abstractmethod
    def set_impairment_profile(self, profile: ImpairmentProfile | dict) -> None:
        """Apply *profile* to ALL configured interfaces (sustained — no auto-restore).

        Cancels any pending auto-restore from a prior :meth:`inject_transient` call
        before applying the new profile.

        :param profile: :class:`~boardfarm3.lib.traffic_control.ImpairmentProfile`
            or plain dict with keys ``latency_ms``, ``jitter_ms``, ``loss_percent``,
            ``bandwidth_limit_mbps`` (dict is auto-converted via
            :func:`~boardfarm3.lib.traffic_control.profile_from_dict`).
        """
        raise NotImplementedError

    @abstractmethod
    def set_interface_profile(
        self, interface: str, profile: ImpairmentProfile | dict
    ) -> None:
        """Apply *profile* to a single named interface (sustained — no auto-restore).

        Cancels any pending auto-restore from a prior :meth:`inject_transient` call
        before applying the new profile.

        :param interface: Kernel interface name (e.g. ``"eth-north"``).  Must be one of
            the interfaces configured for this device.
        :param profile: :class:`~boardfarm3.lib.traffic_control.ImpairmentProfile`
            or plain dict (auto-converted).
        :raises ValueError: if *interface* is not in the configured interface set.
        """
        raise NotImplementedError

    @abstractmethod
    def get_interface_profile(self, interface: str) -> ImpairmentProfile:
        """Return the current impairment parameters for *interface* from the kernel.

        Never returns cached in-memory state — always queries the live hardware or
        kernel qdisc.  If no impairment is active, returns a zero-impairment profile.

        :param interface: Kernel interface name (e.g. ``"eth-north"``).
        :return: Current :class:`~boardfarm3.lib.traffic_control.ImpairmentProfile`
            for that interface.
        :raises ValueError: if *interface* is not in the configured interface set.
        """
        raise NotImplementedError

    @abstractmethod
    def get_interface_profiles(self) -> dict[str, ImpairmentProfile]:
        """Return the current impairment parameters for ALL configured interfaces.

        Returns a ``dict`` keyed by interface name.  Each value is read from the kernel
        on every call — no caching.

        :return: ``{interface_name: ImpairmentProfile}`` for every configured interface.
        """
        raise NotImplementedError

    @abstractmethod
    def clear(self) -> None:
        """Remove all impairments from ALL interfaces (return link to default state).

        Cancels any pending auto-restore from a prior :meth:`inject_transient` call
        before clearing.
        """
        raise NotImplementedError

    @abstractmethod
    def inject_transient(
        self,
        event: str,
        duration_ms: int,
        **kwargs: float | int,
    ) -> None:
        """Inject a timed transient impairment event on ALL interfaces; returns immediately.

        Reads the current per-interface profiles, applies the transient condition to all
        interfaces, and schedules automatic restoration of each interface to its previous
        profile after ``duration_ms``.  The caller never needs to restore state.

        The transient profile is built from the first configured interface's current
        profile as the baseline.  For symmetric testbeds (all interfaces with the same
        profile), this is always correct.

        Supported events:

        ``"blackout"``
            100 % packet loss — simulates complete link failure.
        ``"brownout"``
            Degraded conditions. Kwargs: ``latency_ms`` (default 200), ``loss_percent`` (default 5.0).
        ``"latency_spike"``
            Temporary high latency. Kwargs: ``spike_latency_ms`` (default 500).
        ``"packet_storm"``
            Burst of packet loss. Kwargs: ``loss_percent`` (default 10.0).

        Calling :meth:`set_impairment_profile`, :meth:`set_interface_profile`,
        :meth:`clear`, or another :meth:`inject_transient` while a restore is pending
        cancels the pending restore before applying the new action.

        :param event: Event type string (``"blackout"``, ``"brownout"``,
            ``"latency_spike"``, ``"packet_storm"``).
        :param duration_ms: Duration of the transient condition in milliseconds.
        :param kwargs: Event-specific parameters (see above).
        """
        raise NotImplementedError
