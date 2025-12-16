"""FSM-based GUI component for comprehensive testing.

This component supports three testing modes:
1. Functional Testing: Business goal verification via device methods
2. Navigation Testing: Graph structure validation and resilience testing
3. Visual Regression: Screenshot capture and comparison

Design Principle: This component provides primitives and returns data.
Tests make assertions. pytest generates reports.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from collections import deque

from model_resilience_core.models import UIState, StateTransition
from model_resilience_core.matching import StateComparer

_LOGGER = logging.getLogger(__name__)


class FsmGuiComponent:
    """Generic FSM GUI component supporting functional, structural, and visual testing."""
    
    def __init__(
        self,
        driver,
        fsm_graph_file: Path,
        default_timeout: int = 30,
        match_threshold: float = 0.80,
        match_weights: Dict[str, float] = None,
        screenshot_dir: Path = None,
        visual_threshold: float = 0.95,
        visual_comparison_method: str = 'auto',
        visual_mask_selectors: List[str] = None
    ):
        """Initialize FSM component.
        
        Args:
            driver: PlaywrightSyncAdapter instance
            fsm_graph_file: Path to fsm_graph.json
            default_timeout: Default timeout in seconds
            match_threshold: State matching threshold (0.0-1.0, default 0.80)
            match_weights: Custom weights for fingerprint matching (None = use defaults)
                          Default: {'semantic': 0.60, 'functional': 0.25, 'structural': 0.10,
                                   'content': 0.04, 'style': 0.01}
            screenshot_dir: Directory for screenshots (None = graph parent dir/screenshots)
            visual_threshold: Visual similarity threshold (0.0-1.0, default 0.95)
            visual_comparison_method: 'auto', 'playwright', or 'ssim'
            visual_mask_selectors: CSS selectors to mask in Playwright comparison
        """
        self._driver = driver
        self._default_timeout = default_timeout
        self._match_threshold = match_threshold
        self._match_weights = match_weights
        self._visual_threshold = visual_threshold
        self._visual_comparison_method = visual_comparison_method
        self._visual_mask_selectors = visual_mask_selectors or []
        
        # Screenshot directory - default to graph parent dir/screenshots
        if screenshot_dir is None:
            screenshot_dir = Path(fsm_graph_file).parent / "screenshots"
        self._screenshot_dir = Path(screenshot_dir)
        self._reference_dir = self._screenshot_dir / "references"
        
        # Create directories
        self._screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._reference_dir.mkdir(parents=True, exist_ok=True)
        
        # FSM graph data
        self._states: Dict[str, UIState] = {}
        self._transitions: List[StateTransition] = []
        self._transition_map: Dict[str, List[StateTransition]] = {}
        self._base_url: str = ''  # Base URL from FSM graph
        
        # State tracking
        self._current_state: Optional[str] = None
        self._state_history: List[dict] = []
        
        # Coverage tracking
        self._visited_states: set = set()
        self._executed_transitions: set = set()
        
        # Load FSM graph
        self._load_fsm_graph(fsm_graph_file)
        
        # StateExplorer components
        self._comparer = StateComparer(weights=match_weights)  # Uses custom or default weights
        
        _LOGGER.info(
            "FsmGuiComponent initialized: %d states, %d transitions, "
            "match_threshold=%.2f, screenshot_dir=%s",
            len(self._states),
            len(self._transitions),
            self._match_threshold,
            self._screenshot_dir
        )
        
        if match_weights:
            _LOGGER.info("Using custom match weights: %s", match_weights)
    
    # ========================================================================
    # CORE PRIMITIVES
    # ========================================================================
    
    def _load_fsm_graph(self, graph_file: Path):
        """Load FSM graph from JSON file."""
        _LOGGER.info("Loading FSM graph from: %s", graph_file)
        
        with open(graph_file, 'r') as f:
            data = json.load(f)
        
        # Extract base URL (needed for constructing full URLs from fragments)
        self._base_url = data.get('base_url', '')
        if self._base_url:
            _LOGGER.debug("Using base URL: %s", self._base_url)
        
        # Parse states (handle both 'states' and 'nodes' formats)
        states_data = data.get('states', data.get('nodes', []))
        for state_data in states_data:
            # Handle node_type vs state format
            if 'node_type' in state_data and state_data['node_type'] == 'state':
                # Map JSON keys to UIState constructor params
                state = UIState(
                    state_id=state_data['id'],
                    state_type=state_data.get('state_type', 'unknown'),
                    fingerprint=state_data.get('fingerprint', {}),
                    verification_logic=state_data.get('verification_logic', {}),
                    element_descriptors=state_data.get('element_descriptors', []),
                    discovered_at=state_data.get('discovered_at', 0.0),
                    metadata=state_data.get('metadata', {}),
                    visited=state_data.get('visited', False),
                    depth=state_data.get('depth', 0)
                )
                self._states[state.state_id] = state
        
        _LOGGER.info("Loaded %d states", len(self._states))
        
        # Parse transitions (handle both 'transitions' and 'edges' formats)
        trans_data = data.get('transitions', data.get('edges', []))
        for trans_dict in trans_data:
            # Handle edge format: source/target vs from_state_id/to_state_id
            if 'edge_type' in trans_dict and trans_dict['edge_type'] == 'transition':
                # Map JSON keys to StateTransition constructor params
                trans = StateTransition(
                    transition_id=trans_dict.get('transition_id', f"{trans_dict['source']}_to_{trans_dict['target']}"),
                    from_state_id=trans_dict.get('source', trans_dict.get('from_state_id', '')),
                    to_state_id=trans_dict.get('target', trans_dict.get('to_state_id', '')),
                    action_type=trans_dict.get('action_type', 'click'),
                    trigger_locators=trans_dict.get('trigger_locators', {}),
                    action_data=trans_dict.get('action_data'),
                    success_rate=trans_dict.get('success_rate', 1.0),
                    metadata=trans_dict.get('metadata', {}),
                    timestamp=trans_dict.get('timestamp')
                )
                
                # Add convenience attributes for finding elements
                if 'trigger_locators' in trans_dict:
                    trigger = trans_dict['trigger_locators']
                    # Extract role and name for element finding
                    trans.element_role = trigger.get('element_type', 'button')
                    trans.element_name = trigger.get('name', '')
                    # Store target URL if it's a navigation action
                    if trans.action_type == 'navigate':
                        # Try multiple sources for URL: direct 'url', 'locators.href', or 'locators.url'
                        url = trigger.get('url', '')
                        if not url and 'locators' in trigger:
                            locators = trigger['locators']
                            url = locators.get('href', locators.get('url', ''))
                        
                        # If URL is a fragment (starts with # or #!), prepend base_url
                        if url and url.startswith('#') and self._base_url:
                            # Remove leading '/' from base_url if present to avoid double slashes
                            base = self._base_url.rstrip('/')
                            url = base + '/' + url
                        trans.target_url = url
                
                self._transitions.append(trans)
                
                # Build transition map
                if trans.from_state_id not in self._transition_map:
                    self._transition_map[trans.from_state_id] = []
                self._transition_map[trans.from_state_id].append(trans)
        
        _LOGGER.info("Loaded %d transitions", len(self._transitions))
    
    def verify_state(self, state_id: str, timeout: int = 5) -> bool:
        """Verify current UI matches expected state.
        
        Args:
            state_id: Expected state ID
            timeout: Timeout in seconds (not currently used, for future enhancement)
            
        Returns:
            True if current UI matches expected state
        """
        if state_id not in self._states:
            _LOGGER.error("State '%s' not found in FSM graph", state_id)
            return False
        
        expected_state = self._states[state_id]
        current_fp = self._driver.capture_fingerprint()
        
        # Use StateComparer's is_match() with custom threshold
        matches = self._comparer.is_match(
            current_fp,
            expected_state.fingerprint,
            threshold=self._match_threshold
        )
        
        # Get similarity for logging
        similarity = self._comparer.calculate_similarity(current_fp, expected_state.fingerprint)
        
        if matches:
            self.set_state(state_id, via_action='verify')
            self._visited_states.add(state_id)
            _LOGGER.info("State verified: %s (similarity: %.2f)", state_id, similarity)
        else:
            _LOGGER.warning(
                "State mismatch: expected %s, similarity: %.2f (threshold: %.2f)",
                state_id, similarity, self._match_threshold
            )
        
        return matches
    
    def find_element(
        self,
        state_id: str,
        role: str,
        name: str = None,
        timeout: int = None
    ):
        """Find element in current state using role-based locators.
        
        Uses Playwright's built-in role-based locators for resilient element finding.
        
        Args:
            state_id: State ID to search in (for validation)
            role: ARIA role (button, link, textbox, etc.)
            name: Accessible name (optional)
            timeout: Timeout in seconds (default: component default)
            
        Returns:
            Playwright Locator object
            
        Raises:
            KeyError: If state not in FSM graph
        """
        if state_id not in self._states:
            raise KeyError(f"State '{state_id}' not in FSM graph")
        
        # Use Playwright's built-in role-based locators (sync API)
        timeout_ms = (timeout or self._default_timeout) * 1000
        
        # Set timeout on page for this operation
        self._driver.page.set_default_timeout(timeout_ms)
        
        if name:
            locator = self._driver.page.get_by_role(role, name=name)
        else:
            locator = self._driver.page.get_by_role(role)
        
        _LOGGER.debug("Finding element: role=%s, name=%s", role, name)
        
        return locator
    
    def find_all_elements(self, state_id: str, role: str = None) -> list:
        """Find all elements in state (optionally filtered by role).
        
        Args:
            state_id: State ID to search in
            role: ARIA role to filter by (None = all elements)
            
        Returns:
            List of element descriptors
        """
        if state_id not in self._states:
            raise KeyError(f"State '{state_id}' not in FSM graph")
        
        state = self._states[state_id]
        
        if role is None:
            return state.element_descriptors
        
        # Filter by role
        return [elem for elem in state.element_descriptors if elem.get('role') == role]
    
    def get_state(self) -> Optional[str]:
        """Get currently tracked state ID.
        
        Returns:
            Current state ID or None
        """
        return self._current_state
    
    def set_state(self, state_id: str, via_action: str = None):
        """Manually set current state (with history tracking).
        
        Args:
            state_id: State ID to set
            via_action: Action that led to this state (for history)
        """
        self._current_state = state_id
        self._visited_states.add(state_id)
        self._state_history.append({
            'state_id': state_id,
            'via_action': via_action,
            'timestamp': None
        })
        _LOGGER.debug("State set to: %s (via: %s)", state_id, via_action)
    
    def get_state_history(self) -> List[dict]:
        """Get state transition history for this session.
        
        Returns:
            List of state history entries
        """
        return self._state_history.copy()
    
    def detect_current_state(self, update_state: bool = True) -> Optional[str]:
        """Detect current state by comparing fingerprints.
        
        Args:
            update_state: If True, update internal state tracking
            
        Returns:
            Detected state ID or None
        """
        current_fp = self._driver.capture_fingerprint()
        
        # Use StateComparer's find_matching_state() with custom threshold
        existing_states = list(self._states.values())
        matched_state, similarity = self._comparer.find_matching_state(
            current_fp,
            existing_states,
            threshold=self._match_threshold
        )
        
        if matched_state:
            if update_state:
                self.set_state(matched_state.state_id, via_action='detect')
            _LOGGER.info("State detected: %s (similarity: %.2f)", matched_state.state_id, similarity)
            return matched_state.state_id
        
        _LOGGER.warning(
            "No matching state found (threshold: %.2f)",
            self._match_threshold
        )
        return None
    
    # ========================================================================
    # MODE 1: FUNCTIONAL TESTING
    # ========================================================================
    
    def navigate_to_state(
        self,
        target_state_id: str,
        max_steps: int = 10,
        record_path: bool = False
    ):
        """Navigate from current state to target state using BFS.
        
        Args:
            target_state_id: Destination state
            max_steps: Maximum navigation steps
            record_path: If True, returns dict with path details
            
        Returns:
            bool: True if successful (record_path=False)
            dict: Navigation details (record_path=True)
        """
        if target_state_id not in self._states:
            _LOGGER.error("Target state '%s' not found", target_state_id)
            return False if not record_path else {'success': False, 'error': 'State not found'}
        
        # Detect current state if unknown
        if not self._current_state:
            _LOGGER.info("Current state unknown, detecting...")
            self.detect_current_state()
        
        if not self._current_state:
            error = "Cannot navigate: current state unknown"
            _LOGGER.error(error)
            return False if not record_path else {'success': False, 'error': error}
        
        # Already there?
        if self._current_state == target_state_id:
            _LOGGER.info("Already in target state: %s", target_state_id)
            return True if not record_path else {'success': True, 'path': [], 'steps': 0}
        
        # Find path using BFS
        path = self._find_state_path(self._current_state, target_state_id, max_steps)
        
        if not path:
            error = f"No path found: {self._current_state} -> {target_state_id}"
            _LOGGER.error(error)
            return False if not record_path else {'success': False, 'error': error}
        
        # Execute path
        _LOGGER.info("Executing navigation path: %d steps", len(path))
        for i, transition in enumerate(path):
            _LOGGER.info("Step %d/%d: %s -> %s", i+1, len(path), 
                        transition.from_state_id, transition.to_state_id)
            if not self._execute_transition(transition):
                error = f"Transition failed: {transition.from_state_id} -> {transition.to_state_id}"
                _LOGGER.error(error)
                return False if not record_path else {
                    'success': False,
                    'error': error,
                    'path': path,
                    'completed_steps': i
                }
        
        # Verify final state
        _LOGGER.info("Verifying final state: %s", target_state_id)
        import time
        time.sleep(1)  # Brief wait for UI to settle
        success = self.verify_state(target_state_id, timeout=10)
        
        if record_path:
            return {'success': success, 'path': path, 'steps': len(path)}
        return success
    
    def _find_state_path(
        self,
        from_state_id: str,
        to_state_id: str,
        max_steps: int
    ) -> Optional[List[StateTransition]]:
        """Find shortest path using BFS.
        
        Args:
            from_state_id: Starting state
            to_state_id: Target state
            max_steps: Maximum path length
            
        Returns:
            List of transitions or None if no path found
        """
        queue = deque([(from_state_id, [])])
        visited = {from_state_id}
        
        while queue:
            current, path = queue.popleft()
            
            if len(path) >= max_steps:
                continue
            
            for transition in self._transition_map.get(current, []):
                next_state = transition.to_state_id
                
                if next_state == to_state_id:
                    return path + [transition]
                
                if next_state not in visited:
                    visited.add(next_state)
                    queue.append((next_state, path + [transition]))
        
        return None
    
    def _execute_transition(self, transition: StateTransition) -> bool:
        """Execute a single state transition.
        
        Args:
            transition: Transition to execute
            
        Returns:
            True if successful
        """
        _LOGGER.info(
            "Executing transition: %s -> %s (%s)",
            transition.from_state_id,
            transition.to_state_id,
            transition.action_type
        )
        
        try:
            if transition.action_type == 'click':
                element = self.find_element(
                    transition.from_state_id,
                    transition.element_role,
                    transition.element_name
                )
                element.click()
            elif transition.action_type == 'navigate':
                self._driver.goto(transition.target_url)
            elif transition.action_type == 'submit':
                element = self.find_element(
                    transition.from_state_id,
                    transition.element_role,
                    transition.element_name
                )
                element.click()
            else:
                _LOGGER.warning("Unknown action type: %s", transition.action_type)
                return False
            
            # Brief wait for transition to complete
            import time
            time.sleep(0.5)
            
            # Track execution
            trans_id = f"{transition.from_state_id}->{transition.to_state_id}"
            self._executed_transitions.add(trans_id)
            
            # Update state
            self.set_state(transition.to_state_id, via_action=transition.action_type)
            return True
            
        except Exception as e:
            _LOGGER.error("Transition execution failed: %s", e, exc_info=True)
            return False
    
    def get_available_transitions(
        self,
        from_state_id: str = None
    ) -> List[StateTransition]:
        """Get all available transitions from a state.
        
        Args:
            from_state_id: State to get transitions from (None = current state)
            
        Returns:
            List of transitions
        """
        if from_state_id is None:
            from_state_id = self._current_state
        
        if from_state_id is None:
            _LOGGER.warning("No current state set")
            return []
        
        return self._transition_map.get(from_state_id, [])
    
    # ========================================================================
    # MODE 2: NAVIGATION/STRUCTURE TESTING
    # ========================================================================
    
    def get_graph_structure(self) -> dict:
        """Export FSM graph structure for graph-based testing.
        
        Returns:
            Dictionary with graph structure information
        """
        return {
            'states': list(self._states.keys()),
            'transitions': [
                {
                    'from': t.from_state_id,
                    'to': t.to_state_id,
                    'action': t.action_type,
                    'element_role': getattr(t, 'element_role', None),
                    'element_name': getattr(t, 'element_name', None)
                }
                for t in self._transitions
            ],
            'state_count': len(self._states),
            'transition_count': len(self._transitions)
        }
    
    def validate_graph_connectivity(self) -> dict:
        """Validate graph structure (dead ends, unreachable states).
        
        Returns:
            Dictionary with validation results
        """
        _LOGGER.info("Validating graph connectivity...")
        
        # Build adjacency list
        adjacency = {state_id: [] for state_id in self._states}
        for transition in self._transitions:
            adjacency[transition.from_state_id].append(transition.to_state_id)
        
        # Find states with no outgoing transitions (dead ends)
        dead_end_states = [
            state_id for state_id, neighbors in adjacency.items()
            if len(neighbors) == 0
        ]
        
        # Find unreachable states (no incoming transitions)
        reachable_states = set()
        for neighbors in adjacency.values():
            reachable_states.update(neighbors)
        
        # Assume first state in graph is entry point
        if self._states:
            first_state = list(self._states.keys())[0]
            reachable_states.add(first_state)
        
        unreachable_states = [
            state_id for state_id in self._states
            if state_id not in reachable_states
        ]
        
        # Check if graph is strongly connected
        is_connected = len(unreachable_states) == 0
        
        result = {
            'is_connected': is_connected,
            'unreachable_states': unreachable_states,
            'dead_end_states': dead_end_states,
            'strongly_connected_components': []  # Simplified - could use networkx
        }
        
        _LOGGER.info(
            "Graph validation: connected=%s, unreachable=%d, dead_ends=%d",
            is_connected, len(unreachable_states), len(dead_end_states)
        )
        
        return result
    
    def execute_random_walk(
        self,
        num_steps: int,
        start_state: str = None,
        coverage_target: float = None
    ) -> dict:
        """Execute random walk for exploration testing.
        
        Args:
            num_steps: Number of transitions to execute
            start_state: Starting state (None = current state)
            coverage_target: Stop when coverage reaches this (0.0-1.0)
            
        Returns:
            Dictionary with walk results
        """
        import random
        
        _LOGGER.info("Starting random walk: %d steps", num_steps)
        
        if start_state:
            if not self.verify_state(start_state):
                return {
                    'path': [],
                    'transitions_executed': [],
                    'coverage': 0.0,
                    'errors': ['Failed to verify start state']
                }
        
        path = []
        errors = []
        
        for step in range(num_steps):
            # Get available transitions
            transitions = self.get_available_transitions()
            
            if not transitions:
                errors.append(f"Dead end at state {self._current_state} (step {step})")
                break
            
            # Choose random transition
            transition = random.choice(transitions)
            
            # Execute it
            if self._execute_transition(transition):
                path.append(self._current_state)
            else:
                errors.append(
                    f"Failed transition: {transition.from_state_id} -> {transition.to_state_id}"
                )
            
            # Check coverage target
            if coverage_target:
                coverage = self.calculate_path_coverage()
                if coverage['state_coverage'] >= coverage_target:
                    _LOGGER.info("Coverage target reached: %.2f", coverage['state_coverage'])
                    break
        
        coverage = self.calculate_path_coverage()
        
        _LOGGER.info(
            "Random walk complete: %d states visited, %.1f%% coverage, %d errors",
            len(path), coverage['state_coverage'] * 100, len(errors)
        )
        
        return {
            'path': path,
            'transitions_executed': list(self._executed_transitions),
            'coverage': coverage['state_coverage'],
            'errors': errors
        }
    
    def calculate_path_coverage(self) -> dict:
        """Calculate coverage metrics for current session.
        
        Returns:
            Dictionary with coverage information
        """
        total_states = len(self._states)
        visited_count = len(self._visited_states)
        
        total_transitions = len(self._transitions)
        executed_count = len(self._executed_transitions)
        
        unvisited_states = set(self._states.keys()) - self._visited_states
        
        return {
            'states_visited': visited_count,
            'total_states': total_states,
            'state_coverage': visited_count / total_states if total_states > 0 else 0.0,
            'transitions_executed': executed_count,
            'total_transitions': total_transitions,
            'transition_coverage': executed_count / total_transitions if total_transitions > 0 else 0.0,
            'unvisited_states': list(unvisited_states),
            'unexecuted_transitions': []  # Could be computed if needed
        }
    
    # ========================================================================
    # MODE 3: VISUAL REGRESSION TESTING
    # ========================================================================
    
    def capture_state_screenshot(
        self,
        state_id: str,
        reference: bool = False
    ) -> Path:
        """Capture screenshot of current state.
        
        Args:
            state_id: State identifier
            reference: If True, save as reference image
            
        Returns:
            Path to saved screenshot
        """
        dir_path = self._reference_dir if reference else self._screenshot_dir
        filename = f"{state_id}.png"
        filepath = dir_path / filename
        
        self._driver.take_screenshot(str(filepath), full_page=True)
        _LOGGER.info("Screenshot saved: %s", filepath)
        
        return filepath
    
    def compare_screenshot_with_reference(
        self,
        state_id: str,
        threshold: float = None,
        comparison_method: str = None,
        mask_selectors: list = None
    ) -> dict:
        """Compare current screenshot with reference using fuzzy matching.
        
        Args:
            state_id: State identifier
            threshold: Similarity threshold (None = use component default)
            comparison_method: 'auto', 'playwright', or 'ssim' (None = use component default)
            mask_selectors: CSS selectors to ignore (None = use component default)
        
        Returns:
            Dictionary with comparison results
        """
        threshold = threshold if threshold is not None else self._visual_threshold
        comparison_method = comparison_method if comparison_method is not None else self._visual_comparison_method
        mask_selectors = mask_selectors if mask_selectors is not None else self._visual_mask_selectors
        
        # Auto-select method based on state type
        if comparison_method == 'auto':
            state = self._states.get(state_id)
            method = 'ssim' if state and state.state_type == 'form' else 'playwright'
            _LOGGER.debug("Auto-selected comparison method: %s for state %s", method, state_id)
        else:
            method = comparison_method
        
        if method == 'playwright':
            return self._compare_playwright(state_id, threshold, mask_selectors)
        elif method == 'ssim':
            return self._compare_ssim(state_id, threshold)
        else:
            raise ValueError(f"Unknown comparison method: {method}")
    
    def _compare_playwright(
        self,
        state_id: str,
        threshold: float,
        mask_selectors: list = None
    ) -> dict:
        """Compare using Playwright's built-in comparison.
        
        Handles anti-aliasing, font rendering, and supports dynamic region masking.
        """
        from playwright.sync_api import expect
        
        reference_path = self._reference_dir / f"{state_id}.png"
        
        if not reference_path.exists():
            _LOGGER.error("Reference image not found: %s", reference_path)
            return {
                'match': False,
                'similarity': 0.0,
                'method': 'playwright',
                'error': 'Reference image not found',
                'diff_image_path': None
            }
        
        try:
            # Build mask list
            masks = []
            if mask_selectors:
                for selector in mask_selectors:
                    try:
                        masks.append(self._driver.page.locator(selector))
                    except Exception as e:
                        _LOGGER.debug("Failed to create mask for selector '%s': %s", selector, e)
            
            # Playwright comparison (threshold is inverse: 0 = strict, 1 = permissive)
            expect(self._driver.page).to_have_screenshot(
                str(reference_path),
                threshold=1.0 - threshold,  # Invert: 0.95 -> 0.05
                mask=masks if masks else None
            )
            
            _LOGGER.info("Playwright comparison passed for state: %s", state_id)
            return {
                'match': True,
                'similarity': 1.0,
                'method': 'playwright',
                'error': None,
                'diff_image_path': None
            }
            
        except AssertionError as e:
            error_msg = str(e)
            _LOGGER.warning(
                "Playwright comparison failed for %s: %s",
                state_id, error_msg
            )
            
            # Diff image is automatically saved by Playwright
            diff_path = self._screenshot_dir / f"{state_id}-diff.png"
            
            return {
                'match': False,
                'similarity': 0.0,  # Playwright doesn't provide exact similarity
                'method': 'playwright',
                'error': error_msg,
                'diff_image_path': diff_path if diff_path.exists() else None
            }
    
    def _compare_ssim(self, state_id: str, threshold: float) -> dict:
        """Compare using SSIM (Structural Similarity Index).
        
        Focuses on layout structure rather than pixel-perfect matching.
        More tolerant of color variations and font changes.
        """
        from PIL import Image
        from skimage.metrics import structural_similarity as ssim
        import numpy as np
        
        # Capture current screenshot
        current_path = self.capture_state_screenshot(state_id, reference=False)
        reference_path = self._reference_dir / f"{state_id}.png"
        
        if not reference_path.exists():
            _LOGGER.error("Reference image not found: %s", reference_path)
            return {
                'match': False,
                'similarity': 0.0,
                'method': 'ssim',
                'error': 'Reference image not found',
                'diff_image_path': None
            }
        
        try:
            # Load images
            current_img = Image.open(current_path).convert('RGB')
            reference_img = Image.open(reference_path).convert('RGB')
            
            # Ensure same size (resize if needed)
            if current_img.size != reference_img.size:
                _LOGGER.warning(
                    "Image size mismatch for %s: %s vs %s, resizing current",
                    state_id, current_img.size, reference_img.size
                )
                current_img = current_img.resize(reference_img.size)
            
            # Convert to numpy arrays
            current_array = np.array(current_img)
            reference_array = np.array(reference_img)
            
            # Calculate SSIM (multichannel for RGB)
            similarity, diff_image = ssim(
                reference_array,
                current_array,
                multichannel=True,
                channel_axis=2,
                full=True
            )
            
            match = similarity >= threshold
            
            # Save diff image if mismatch
            diff_path = None
            if not match:
                diff_path = self._screenshot_dir / f"{state_id}_ssim_diff.png"
                # Normalize diff image to 0-255 range (inverted: white = different)
                diff_normalized = ((1.0 - diff_image) * 255).astype(np.uint8)
                Image.fromarray(diff_normalized).save(diff_path)
                
                _LOGGER.warning(
                    "SSIM comparison failed for %s: %.2f%% (threshold: %.2f%%)",
                    state_id, similarity * 100, threshold * 100
                )
            else:
                _LOGGER.info("SSIM comparison passed for %s: %.2f%%", state_id, similarity * 100)
            
            return {
                'match': match,
                'similarity': similarity,
                'method': 'ssim',
                'error': None,
                'diff_image_path': diff_path
            }
            
        except Exception as e:
            _LOGGER.error("SSIM comparison error for %s: %s", state_id, e, exc_info=True)
            return {
                'match': False,
                'similarity': 0.0,
                'method': 'ssim',
                'error': str(e),
                'diff_image_path': None
            }
    
    def capture_all_states_screenshots(
        self,
        reference: bool = False,
        max_time: int = 300
    ) -> dict:
        """Navigate and capture all state screenshots.
        
        Args:
            reference: If True, save as reference images
            max_time: Maximum time in seconds
            
        Returns:
            Dictionary with capture results
        """
        import time
        
        _LOGGER.info("Capturing screenshots for all states (reference=%s)", reference)
        
        start_time = time.time()
        captured = []
        failed = []
        screenshots = {}
        
        for state_id in self._states:
            # Check timeout
            if time.time() - start_time > max_time:
                _LOGGER.warning("Timeout reached, stopping screenshot capture")
                break
            
            try:
                # Navigate to state
                _LOGGER.info("Navigating to state: %s", state_id)
                if self.navigate_to_state(state_id, max_steps=10):
                    # Capture screenshot
                    path = self.capture_state_screenshot(state_id, reference=reference)
                    captured.append(state_id)
                    screenshots[state_id] = path
                else:
                    _LOGGER.error("Failed to navigate to state: %s", state_id)
                    failed.append(state_id)
            except Exception as e:
                _LOGGER.error("Failed to capture %s: %s", state_id, e)
                failed.append(state_id)
        
        coverage = len(captured) / len(self._states) if self._states else 0.0
        
        _LOGGER.info(
            "Screenshot capture complete: %d captured, %d failed, %.1f%% coverage",
            len(captured), len(failed), coverage * 100
        )
        
        return {
            'captured': captured,
            'failed': failed,
            'screenshots': screenshots,
            'coverage': coverage
        }
    
    def validate_all_states_visually(
        self,
        threshold: float = None
    ) -> dict:
        """Navigate and compare all states with references.
        
        Args:
            threshold: Similarity threshold (None = use component default)
            
        Returns:
            Dictionary with validation results
        """
        threshold = threshold if threshold is not None else self._visual_threshold
        
        _LOGGER.info("Validating all states visually (threshold=%.2f)", threshold)
        
        passed = []
        failed = []
        results = {}
        
        for state_id in self._states:
            try:
                # Navigate to state
                _LOGGER.info("Validating state: %s", state_id)
                if self.navigate_to_state(state_id, max_steps=10):
                    # Compare with reference
                    comparison = self.compare_screenshot_with_reference(
                        state_id,
                        threshold=threshold
                    )
                    results[state_id] = comparison
                    
                    if comparison['match']:
                        passed.append(state_id)
                    else:
                        failed.append(state_id)
                else:
                    _LOGGER.error("Failed to navigate to state: %s", state_id)
                    failed.append(state_id)
                    results[state_id] = {
                        'match': False,
                        'similarity': 0.0,
                        'error': 'Navigation failed'
                    }
            except Exception as e:
                _LOGGER.error("Failed to validate %s: %s", state_id, e)
                failed.append(state_id)
                results[state_id] = {
                    'match': False,
                    'similarity': 0.0,
                    'error': str(e)
                }
        
        overall_pass = len(failed) == 0
        
        _LOGGER.info(
            "Visual validation complete: %d passed, %d failed, overall: %s",
            len(passed), len(failed), "PASS" if overall_pass else "FAIL"
        )
        
        return {
            'passed': passed,
            'failed': failed,
            'results': results,
            'overall_pass': overall_pass
        }
    
    # ========================================================================
    # METADATA ACCESS (for test assertions)
    # ========================================================================
    
    def get_state_metadata(self, state_id: str) -> dict:
        """Get complete metadata for a state from FSM graph.
        
        Args:
            state_id: State ID
            
        Returns:
            Dictionary with state metadata
            
        Raises:
            KeyError: If state not in graph
        """
        if state_id not in self._states:
            raise KeyError(f"State '{state_id}' not in FSM graph")
        
        state = self._states[state_id]
        
        # Extract URL from fingerprint if available
        url = state.fingerprint.get('url_pattern', None)
        
        return {
            'id': state.state_id,
            'state_type': state.state_type,
            'url': url,
            'fingerprint': state.fingerprint,
            'element_descriptors': state.element_descriptors,
            'discovered_at': state.discovered_at
        }
    
    def get_transition_metadata(
        self,
        from_state: str,
        to_state: str
    ) -> Optional[StateTransition]:
        """Get transition metadata between two states.
        
        Args:
            from_state: Source state ID
            to_state: Target state ID
            
        Returns:
            StateTransition object or None if no direct transition
        """
        for transition in self._transition_map.get(from_state, []):
            if transition.to_state_id == to_state:
                return transition
        return None
