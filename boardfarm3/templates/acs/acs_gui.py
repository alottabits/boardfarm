"""ACS GUI Template."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from boardfarm3.templates.acs.acs import ACS


class ACSGUI(ABC):
    """ACS GUI Template."""

    def __init__(self, device: ACS) -> None:
        """Initialize ACS GUI.
        
        :param device: Parent ACS device
        :type device: ACS
        """
        self.device = device
    
    @property
    def config(self) -> dict:
        """Device config."""
        return self.device.config

    @abstractmethod
    def login(self) -> None:
        """Login to the ACS GUI."""
        raise NotImplementedError
