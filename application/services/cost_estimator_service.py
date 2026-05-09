"""Rough token/cost estimator.

This is a heuristic estimator to help understand session cost.
It does NOT call any external APIs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class TokenEstimate:
    """Estimated token usage."""

    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class CostEstimatorService:
    """Estimate tokens by text length."""

    def estimate(self, *, input_text: str, expected_output_tokens: int = 2000) -> TokenEstimate:
        # Very rough: ~4 chars per token for Latin/Cyrillic mixed text.
        input_tokens = int(math.ceil(len(input_text) / 4.0))
        return TokenEstimate(input_tokens=input_tokens, output_tokens=int(expected_output_tokens))

