"""Schedule importers.

Primary, cross-platform (Linux-testable) path: MS Project XML and Primavera XER
(pure-Python) plus native ``.mpp`` via MPXJ-as-subprocess. COM automation is an
optional Windows-only enhancement (authored, validated locally; never the only
path). See docs/ARCHITECTURE.md for the full fallback chain.
"""
