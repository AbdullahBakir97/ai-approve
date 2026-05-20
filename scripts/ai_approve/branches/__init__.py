"""Specialized review branches that augment the standard Pass 2 review.

Each branch returns a partial-Pass-2-shaped dict; `aggregator.py` merges
them via strictest-wins on verdict. See design spec §9.
"""
