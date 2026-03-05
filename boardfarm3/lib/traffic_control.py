"""Traffic control library — ImpairmentProfile schema and Linux tc netem helpers.

This module is the sole source of truth for:

- :class:`ImpairmentProfile` — the parameter object passed to / returned from every
  TrafficController method.  One profile describes one interface — asymmetry across
  links is expressed by assigning *different* profiles to *different* interfaces.
- :func:`profile_from_dict` — converts a plain dict (e.g., from env JSON) to a profile.
- :func:`apply_tc_profile` — translates a profile to ``tc qdisc`` shell commands and
  runs them on a single interface.
- :func:`read_tc_profile` — reads back the current profile from the kernel via
  ``tc -j qdisc show`` (JSON output) for a single interface.  Never uses in-memory cache.
- :func:`clear_tc_profile` — removes all qdiscs from an interface.
- :func:`_build_transient_profile` — constructs the transient ImpairmentProfile for a
  named event type.  Used by
  :class:`~boardfarm3.devices.linux_traffic_controller.LinuxTrafficController`.

See: ``docs/Traffic_Management_Components_Architecture.md``
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from boardfarm3.lib.boardfarm_pexpect import BoardfarmPexpect

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ImpairmentProfile:
    """Parameters for network impairment applied via Linux tc netem on a **single interface**.

    One :class:`ImpairmentProfile` describes the impairment for one kernel interface.
    Asymmetry across a link (e.g. upstream bandwidth ≠ downstream bandwidth) is expressed
    by assigning *different* profiles to *different* interfaces, not by fields within a
    single profile.

    ``bandwidth_limit_mbps = None`` means no rate limit (no TBF qdisc).  ``0`` is *not*
    used for "no limit" — use ``None`` instead.  To simulate a blackout, set
    ``loss_percent = 100.0``; do *not* set bandwidth to 0.
    """

    latency_ms: int
    """One-way delay (ms)."""

    jitter_ms: int
    """Per-packet delay variation (±ms, normal distribution)."""

    loss_percent: float
    """Packet loss fraction (0.0 – 100.0)."""

    bandwidth_limit_mbps: int | None
    """Bandwidth cap (Mbps).  ``None`` = no cap."""

    reorder_percent: float = 0.0
    """Fraction of packets to reorder (%). Requires ``latency_ms > 0``."""

    corrupt_percent: float = 0.0
    """Fraction of packets to corrupt (%)."""

    duplicate_percent: float = 0.0
    """Fraction of packets to duplicate (%)."""


def profile_from_dict(data: dict) -> ImpairmentProfile:
    """Parse a plain dict to an :class:`ImpairmentProfile`.

    Required keys: ``latency_ms``, ``jitter_ms``, ``loss_percent``.
    Optional: ``bandwidth_limit_mbps``, ``reorder_percent``, ``corrupt_percent``,
    ``duplicate_percent``.

    :param data: dict from env JSON or test code.
    :return: Parsed :class:`ImpairmentProfile`.
    :raises KeyError: if a required key is missing.
    """
    return ImpairmentProfile(
        latency_ms=int(data["latency_ms"]),
        jitter_ms=int(data["jitter_ms"]),
        loss_percent=float(data["loss_percent"]),
        bandwidth_limit_mbps=(
            int(data["bandwidth_limit_mbps"])
            if data.get("bandwidth_limit_mbps") is not None
            else None
        ),
        reorder_percent=float(data.get("reorder_percent", 0.0)),
        corrupt_percent=float(data.get("corrupt_percent", 0.0)),
        duplicate_percent=float(data.get("duplicate_percent", 0.0)),
    )


# ---------------------------------------------------------------------------
# Linux tc helpers
# ---------------------------------------------------------------------------


def _build_netem_args(
    latency_ms: int,
    jitter_ms: int,
    loss_percent: float,
    reorder_percent: float = 0.0,
    corrupt_percent: float = 0.0,
    duplicate_percent: float = 0.0,
) -> str:
    """Build the argument string for ``tc qdisc ... netem ...``.

    Returns an empty string when all parameters are zero (no netem needed).
    """
    parts: list[str] = []

    if latency_ms > 0 or jitter_ms > 0:
        delay = f"delay {latency_ms}ms"
        if jitter_ms > 0:
            # distribution normal makes jitter Gaussian; without it, tc uses uniform.
            delay += f" {jitter_ms}ms distribution normal"
        parts.append(delay)

    if loss_percent > 0.0:
        # tc netem accepts fractional percentages (e.g. 0.1%)
        parts.append(f"loss {loss_percent:.4f}%")

    if duplicate_percent > 0.0:
        parts.append(f"duplicate {duplicate_percent:.4f}%")

    if corrupt_percent > 0.0:
        parts.append(f"corrupt {corrupt_percent:.4f}%")

    if reorder_percent > 0.0 and latency_ms > 0:
        # tc netem reorder requires a base delay to be set
        parts.append(f"reorder {reorder_percent:.4f}%")

    return " ".join(parts)


def _apply_qdisc(
    console: BoardfarmPexpect,
    iface: str,
    latency_ms: int,
    jitter_ms: int,
    loss_percent: float,
    bandwidth_limit_mbps: int | None,
    reorder_percent: float = 0.0,
    corrupt_percent: float = 0.0,
    duplicate_percent: float = 0.0,
) -> None:
    """Apply tc netem (+ optional TBF) to a single interface.

    Always deletes the existing root qdisc first so the call is idempotent.

    With bandwidth limit: stacks netem (root, handle 1:) → TBF (parent 1:1, handle 10:).
    Without bandwidth limit: adds netem as root qdisc directly.
    If all impairment parameters are zero and there is no bandwidth cap, the interface
    is left with the kernel default qdisc (no netem added).
    """
    console.execute_command(f"tc qdisc del dev {iface} root 2>/dev/null || true")

    netem_args = _build_netem_args(
        latency_ms,
        jitter_ms,
        loss_percent,
        reorder_percent,
        corrupt_percent,
        duplicate_percent,
    )

    if bandwidth_limit_mbps is not None and bandwidth_limit_mbps > 0:
        # Stack: netem root → TBF child for rate limiting.
        # Burst: sized for ~10 ms of traffic at the configured rate, min 1500 bytes.
        burst_bytes = max(1500, bandwidth_limit_mbps * 1_000_000 // 8 // 100)
        netem_str = netem_args if netem_args else ""
        console.execute_command(
            f"tc qdisc add dev {iface} root handle 1: netem {netem_str}".rstrip()
        )
        console.execute_command(
            f"tc qdisc add dev {iface} parent 1:1 handle 10: "
            f"tbf rate {bandwidth_limit_mbps}mbit burst {burst_bytes} latency 400ms"
        )
    elif netem_args:
        console.execute_command(
            f"tc qdisc add dev {iface} root netem {netem_args}"
        )
    # else: no impairment requested — interface returns to kernel default (noqueue/pfifo_fast)


def apply_tc_profile(
    console: BoardfarmPexpect,
    iface: str,
    profile: ImpairmentProfile,
) -> None:
    """Apply *profile* to a single interface via ``tc netem``.

    This is the primary public function for setting impairment on one interface.
    For multi-interface TCs, call once per interface with the appropriate profile.

    :param console: Active console for the TC device.
    :param iface: Kernel interface name (e.g. ``"eth-north"``).
    :param profile: Impairment parameters to apply.
    """
    _apply_qdisc(
        console,
        iface,
        profile.latency_ms,
        profile.jitter_ms,
        profile.loss_percent,
        profile.bandwidth_limit_mbps,
        profile.reorder_percent,
        profile.corrupt_percent,
        profile.duplicate_percent,
    )


def clear_tc_profile(console: BoardfarmPexpect, iface: str) -> None:
    """Remove all tc qdiscs from *iface*, returning it to the kernel default.

    Safe to call when no qdisc is active (error from ``tc`` is suppressed).

    :param console: Active console for the TC device.
    :param iface: Interface name (e.g. ``"eth-north"``).
    """
    console.execute_command(f"tc qdisc del dev {iface} root 2>/dev/null || true")


# ---------------------------------------------------------------------------
# Kernel state reading
# ---------------------------------------------------------------------------


def _parse_tc_json_output(raw: str) -> list[dict]:
    """Extract and parse the JSON array from ``tc -j qdisc show`` output.

    The console output may contain a command echo or trailing prompt before/after
    the JSON.  We scan for the opening ``[`` to tolerate this.

    :param raw: Raw console output from ``tc -j qdisc show``.
    :return: Parsed list of qdisc dicts, or empty list on failure.
    """
    raw = raw.strip()
    idx = raw.find("[")
    if idx < 0:
        _LOGGER.debug("No JSON array found in tc output: %r", raw[:200])
        return []
    try:
        return json.loads(raw[idx:])  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        _LOGGER.warning("Failed to parse tc JSON output: %r", raw[:200])
        return []


def _extract_profile_from_qdiscs(
    qdiscs: list[dict],
) -> tuple[int, int, float, int | None]:
    """Extract ``(latency_ms, jitter_ms, loss_percent, bandwidth_limit_mbps)`` from qdiscs.

    Field mapping from ``tc -j qdisc show`` JSON:

    - ``netem.options.delay.delay``       → ``latency_ms``  (seconds → ms, ×1000)
    - ``netem.options.delay.jitter``      → ``jitter_ms``   (seconds → ms, ×1000)
    - ``netem.options.loss-random.loss``  → ``loss_percent`` (fraction → %, ×100)
    - ``tbf.options.rate``                → ``bandwidth_limit_mbps`` (B/s → Mbps, ×8÷1 000 000)

    Returns zero-impairment values when no netem qdisc is present.
    """
    latency_ms = 0
    jitter_ms = 0
    loss_percent = 0.0
    bandwidth_limit_mbps: int | None = None

    for q in qdiscs:
        kind = q.get("kind", "")
        opts = q.get("options", {})

        if kind == "netem":
            delay_opts = opts.get("delay", {})
            latency_ms = round(delay_opts.get("delay", 0.0) * 1000)
            jitter_ms = round(delay_opts.get("jitter", 0.0) * 1000)
            loss_fraction = opts.get("loss-random", {}).get("loss", 0.0)
            loss_percent = round(loss_fraction * 100, 4)

        elif kind == "tbf":
            # tc -j qdisc show reports TBF rate as a plain int in bytes/s, not a nested dict.
            # Example: {"kind":"tbf","options":{"rate":125000000,"burst":...}}
            # 125 000 000 B/s × 8 / 1 000 000 = 1000 Mbit/s
            rate_bps = opts.get("rate", 0)
            if isinstance(rate_bps, dict):
                rate_bps = rate_bps.get("rate", 0)
            if rate_bps > 0:
                bandwidth_limit_mbps = round(rate_bps * 8 / 1_000_000)

    return latency_ms, jitter_ms, loss_percent, bandwidth_limit_mbps


def read_tc_profile(
    console: BoardfarmPexpect,
    iface: str,
) -> ImpairmentProfile:
    """Read the current impairment profile for *iface* from the kernel.

    Parses ``tc -j qdisc show dev <iface>`` JSON.  Always reads from the kernel —
    never returns cached in-memory state.  Returns a zero-impairment profile when no
    netem qdisc is present.

    :param console: Active console for the TC device.
    :param iface: Kernel interface name (e.g. ``"eth-north"``).
    :return: Current :class:`ImpairmentProfile` for that interface.
    """
    out = console.execute_command(f"tc -j qdisc show dev {iface}")
    qdiscs = _parse_tc_json_output(out)
    latency_ms, jitter_ms, loss_percent, bandwidth_limit_mbps = (
        _extract_profile_from_qdiscs(qdiscs)
    )
    return ImpairmentProfile(
        latency_ms=latency_ms,
        jitter_ms=jitter_ms,
        loss_percent=loss_percent,
        bandwidth_limit_mbps=bandwidth_limit_mbps,
    )


# ---------------------------------------------------------------------------
# Transient event builder
# ---------------------------------------------------------------------------


def _build_transient_profile(
    event: str,
    previous: ImpairmentProfile,
    **kwargs: float | int,
) -> ImpairmentProfile:
    """Construct an :class:`ImpairmentProfile` for a named transient event.

    *previous* is used as the baseline; only the fields relevant to the event type
    are overridden.

    Supported events:

    ``"blackout"``
        100 % packet loss; preserves baseline latency/jitter so that the DUT receives
        some packets (ICMP keepalives) via any still-open paths — set ``loss 100%``
        rather than a bandwidth cap of 0 so that ``tc`` does not reject invalid params.
    ``"brownout"``
        Degraded link. Kwargs: ``latency_ms`` (default 200), ``jitter_ms`` (default
        *previous.jitter_ms*), ``loss_percent`` (default 5.0).
    ``"latency_spike"``
        Temporary high latency. Kwargs: ``spike_latency_ms`` (default 500).
    ``"packet_storm"``
        Burst of packet loss. Kwargs: ``loss_percent`` (default 10.0).

    :param event: Event type string.
    :param previous: Current profile read from the kernel (used as baseline).
    :param kwargs: Event-specific parameter overrides.
    :return: Transient :class:`ImpairmentProfile`.
    :raises ValueError: if *event* is not one of the supported strings.
    """
    if event == "blackout":
        return ImpairmentProfile(
            latency_ms=previous.latency_ms,
            jitter_ms=previous.jitter_ms,
            loss_percent=100.0,
            bandwidth_limit_mbps=None,
        )
    if event == "brownout":
        return ImpairmentProfile(
            latency_ms=int(kwargs.get("latency_ms", 200)),
            jitter_ms=int(kwargs.get("jitter_ms", previous.jitter_ms)),
            loss_percent=float(kwargs.get("loss_percent", 5.0)),
            bandwidth_limit_mbps=previous.bandwidth_limit_mbps,
        )
    if event == "latency_spike":
        return ImpairmentProfile(
            latency_ms=int(kwargs.get("spike_latency_ms", 500)),
            jitter_ms=previous.jitter_ms,
            loss_percent=previous.loss_percent,
            bandwidth_limit_mbps=previous.bandwidth_limit_mbps,
        )
    if event == "packet_storm":
        return ImpairmentProfile(
            latency_ms=previous.latency_ms,
            jitter_ms=previous.jitter_ms,
            loss_percent=float(kwargs.get("loss_percent", 10.0)),
            bandwidth_limit_mbps=previous.bandwidth_limit_mbps,
        )
    raise ValueError(
        f"Unknown transient event: {event!r}. "
        "Expected one of: blackout, brownout, latency_spike, packet_storm."
    )
