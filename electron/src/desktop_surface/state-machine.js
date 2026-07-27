"use strict";

/**
 * Desktop Surface (Dynamic Island) visible states.
 *
 * State graph:
 *   collapsed ──hover──▶ peek
 *   peek ──click──▶ expanded
 *   peek ──mouse-leave──▶ collapsed
 *   expanded ──select-tool──▶ tool-panel
 *   expanded ──blur──▶ collapsed
 *   tool-panel ──close-panel──▶ expanded
 */
const IslandState = Object.freeze({
  COLLAPSED: "collapsed",
  PEEK: "peek",
  EXPANDED: "expanded",
  TOOL_PANEL: "tool-panel",
});

// Allowed outgoing transitions per source state.
const ALLOWED_TRANSITIONS = Object.freeze({
  [IslandState.COLLAPSED]: Object.freeze([IslandState.PEEK]),
  [IslandState.PEEK]: Object.freeze([IslandState.EXPANDED, IslandState.COLLAPSED]),
  [IslandState.EXPANDED]: Object.freeze([IslandState.TOOL_PANEL, IslandState.COLLAPSED]),
  [IslandState.TOOL_PANEL]: Object.freeze([IslandState.EXPANDED]),
});

const VALID_STATES = new Set(Object.values(IslandState));

class IslandStateMachine {
  /**
   * @param {string} [initialState=IslandState.COLLAPSED]
   * @param {(fromState: string, toState: string, timestamp: number) => void} [onStateChange]
   */
  constructor(initialState, onStateChange) {
    const start = initialState ?? IslandState.COLLAPSED;
    if (!VALID_STATES.has(start)) {
      throw new Error(`Invalid initial state: ${start}`);
    }
    this._state = start;
    this._onStateChange = typeof onStateChange === "function" ? onStateChange : null;
  }

  /**
   * Query whether transitioning to `targetState` is currently allowed.
   * @param {string} targetState
   * @returns {boolean}
   */
  canTransition(targetState) {
    if (!VALID_STATES.has(targetState)) return false;
    if (targetState === this._state) return false;
    const allowed = ALLOWED_TRANSITIONS[this._state];
    return allowed !== undefined && allowed.includes(targetState);
  }

  /**
   * Attempt to transition to `targetState`.
   * @param {string} targetState
   * @returns {boolean} true if the transition occurred, false otherwise
   */
  transition(targetState) {
    if (!this.canTransition(targetState)) return false;
    const fromState = this._state;
    this._state = targetState;
    if (this._onStateChange) {
      this._onStateChange(fromState, targetState, Date.now());
    }
    return true;
  }

  /**
   * @returns {string} current state
   */
  getState() {
    return this._state;
  }
}

module.exports = { IslandState, IslandStateMachine };
