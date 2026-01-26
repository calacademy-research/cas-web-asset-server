"""
GenerationStats - Statistics for a generation run.
"""

import time
from dataclasses import dataclass, field
from typing import List


@dataclass
class GenerationStats:
    """
    Statistics for a generation run.
    
    Attributes:
        total_to_process: Total images needing thumbnails
        processed: Successfully generated
        skipped: Skipped (already exists or filtered)
        errors: Failed to generate
        bytes_generated: Total bytes of thumbnails generated
        start_time: Start timestamp
        error_details: List of error messages
    """
    total_to_process: int = 0
    processed: int = 0
    skipped: int = 0
    errors: int = 0
    bytes_generated: int = 0
    start_time: float = field(default_factory=time.time)
    error_details: List[str] = field(default_factory=list)
    
    @property
    def elapsed_seconds(self) -> float:
        """Elapsed time in seconds."""
        return time.time() - self.start_time
    
    @property
    def rate_per_second(self) -> float:
        """Processing rate in images per second."""
        if self.elapsed_seconds > 0:
            return self.processed / self.elapsed_seconds
        return 0.0
    
    @property
    def rate_per_minute(self) -> float:
        """Processing rate in images per minute."""
        return self.rate_per_second * 60
    
    @property
    def estimated_remaining_seconds(self) -> float:
        """Estimated time remaining in seconds."""
        remaining = self.total_to_process - self.processed - self.skipped - self.errors
        if self.rate_per_second > 0:
            return remaining / self.rate_per_second
        return 0.0
    
    @property
    def completed_count(self) -> int:
        """Total completed (processed + skipped + errors)."""
        return self.processed + self.skipped + self.errors
    
    @property
    def remaining_count(self) -> int:
        """Remaining to process."""
        return self.total_to_process - self.completed_count
