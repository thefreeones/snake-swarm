"""
Clean sample — should produce 0 issues.
"""
import os
from typing import List, Optional


def calculate_average(numbers: List[float]) -> float:
    """Return the average of a list of numbers."""
    if not numbers:
        raise ValueError("Cannot calculate average of empty list")
    return sum(numbers) / len(numbers)


def find_max(values: List[int]) -> Optional[int]:
    """Return the maximum value or None if empty."""
    if not values:
        return None
    return max(values)


class DataProcessor:
    """A simple data processor with no anti-patterns."""

    def __init__(self, data: List[float]) -> None:
        self.data = data

    def process(self) -> List[float]:
        """Filter out negative values."""
        return [x for x in self.data if x >= 0]

    def summary(self) -> dict:
        """Return summary statistics."""
        return {
            "count": len(self.data),
            "average": calculate_average(self.data),
        }
