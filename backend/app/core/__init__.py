"""Pure, deterministic domain core (no database, no I/O).

The same engine is used by the live controller (persisted through SQLAlchemy)
and by the experiment runner (in-memory replay), so live behaviour and
experimental results are produced by exactly the same code.
"""
