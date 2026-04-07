# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1] - 2026-04-06

### Fixed
- `__repr__`, `__str__`, and `__format__` no longer call `_rg_check`. These are
  diagnostic/observational operations and must not influence the detection state
  machine or trigger false-positive race errors in hot concurrent paths.
- `__int__`, `__float__`, and `__index__` now call `_rg_check("read")`. Previously
  these bypassed detection entirely, allowing silent unmonitored numeric reads.
- `__enter__` and `__exit__` no longer call `_rg_check`. Lock acquisition in
  `__enter__` is itself the synchronization event; a redundant `"read"` pre-check
  incorrectly suppressed concurrent-entry detection (read+read was treated as safe).
- Removed duplicate `# --- Context manager ---` section comment.
- `configure()` docstring now explicitly documents that `enabled=False` is
  non-retroactive: proxies created before the call continue to monitor accesses.
- Updated `tests/proof/test_semantic_race.py` to properly document the `AtomicGroup` 
  solution for cross-object semantic invariant violations, adding sequential locking proofs.

## [0.2.0] - 2026-04-02

### Added
- **Asyncio Support**: Added tracking for `asyncio` task identities to detect races between pure async tasks or mixed thread/async environments.
- **Deep Proxying**: Automatic protection of nested mutable objects (e.g., lists inside dictionaries).
- **Strict Mode**: Optional deterministic race detection that bypasses time-proximity heuristics.
- **Internal Re-entrancy**: Upgraded internal locking to `threading.RLock()` to support recursive synchronization patterns.
- **Value Wrapper**: New `raceguard.Value` container for protecting shared immutable primitives.
- **Synchronization API**: Added `raceguard.reset(obj)` for explicit memory barriers and `raceguard.unbind(obj)` for identity checks.
- **Iterator Protection**: Integrated `_ProxyIterator` to monitor long-running loops for concurrent modifications.

### Changed
- Refactored proxy architecture to use shared `_SyncMemory` state across parent-child hierarchies.
- Improved error messages to include better location context.
- Optimized performance by replacing immediate stack capture with lazy frame inspection.

### Fixed
- Fixed deadlocks when using `locked()` or `@with_lock` recursively on the same thread.
- Resolved false positives caused by missing lock-hold detection on re-entrant locks.

## [0.1.0] - 2026-04-01

### Added
- Initial release with basic threading race detection.
- Heuristic-based un-synchronized access identification.
- Warn, Raised, and Log modes.
- Core `protect()`, `locked()`, and `with_lock` APIs.
