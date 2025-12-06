"""GUI components for UI testing."""

from boardfarm3.lib.gui.base_gui_component import BaseGuiComponent
from boardfarm3.lib.gui.navigation_generator import NavigationGenerator
from boardfarm3.lib.gui.selector_generator import SelectorGenerator
from boardfarm3.lib.gui.ui_graph import UIGraph

__all__ = [
    "BaseGuiComponent",
    "UIGraph",
    "SelectorGenerator",
    "NavigationGenerator",
]

