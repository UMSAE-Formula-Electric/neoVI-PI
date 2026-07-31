"""
tests — the first test package in this repository (D-09).

Introduces pytest as the project's test framework. `conftest.py` provides
session-scoped fixtures loading `epbr2026_DBC_v1.0.dbc` once so individual
test modules never re-parse the DBC.
"""
