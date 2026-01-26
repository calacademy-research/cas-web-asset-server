"""
GenerationProgress - Tracks and displays generation progress.
"""

import logging
from typing import Optional

from .generation_stats import GenerationStats
from .image_record import ImageRecord


class GenerationProgress:
    """
    Tracks and displays generation progress with optional per-file output.
    """
    
    def __init__(
        self,
        show_files: bool = False,
        log_interval: int = 100,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize progress tracker.
        
        Args:
            show_files: If True, print each file as it's processed
            log_interval: Log summary progress every N images (when not show_files)
            logger: Optional logger instance
        """
        self.show_files = show_files
        self.log_interval = log_interval
        self.logger = logger or logging.getLogger(__name__)
        self.last_logged = 0
    
    def on_file_processed(
        self, 
        record: ImageRecord, 
        success: bool, 
        thumb_size: Optional[int] = None,
        error: Optional[str] = None
    ) -> None:
        """
        Called when a file is processed.
        
        Args:
            record: The image record
            success: Whether generation succeeded
            thumb_size: Size of generated thumbnail (if success)
            error: Error message (if failed)
        """
        if self.show_files:
            if success:
                size_str = self._format_bytes(thumb_size) if thumb_size else "unknown"
                print(f"  [OK] {record.filename} -> thumbnail generated ({size_str})")
            else:
                print(f"  [ERROR] {record.filename} -> {error or 'failed'}")
    
    def on_file_skipped(self, record: ImageRecord, reason: str) -> None:
        """Called when a file is skipped."""
        if self.show_files:
            print(f"  [SKIP] {record.filename} -> {reason}")
    
    def on_progress_update(self, stats: GenerationStats) -> None:
        """
        Called periodically to report overall progress.
        
        Args:
            stats: Current generation statistics
        """
        total_done = stats.completed_count
        
        if not self.show_files and total_done - self.last_logged >= self.log_interval:
            self.last_logged = total_done
            
            remaining = stats.remaining_count
            eta_minutes = stats.estimated_remaining_seconds / 60
            
            self.logger.info(
                f"Progress: {stats.processed} generated, {stats.errors} errors "
                f"({stats.rate_per_minute:.1f}/min, "
                f"~{eta_minutes:.0f}m remaining, {remaining} left)"
            )
    
    def on_dry_run(self, record: ImageRecord) -> None:
        """Called in dry-run mode."""
        if self.show_files:
            print(f"  [DRY RUN] {record.filename} -> would generate thumbnail")
    
    @staticmethod
    def _format_bytes(bytes_val: Optional[int]) -> str:
        """Format bytes as human-readable string."""
        if bytes_val is None:
            return "unknown"
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_val < 1024:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.1f} TB"
    
    def __call__(self, stats: GenerationStats) -> None:
        """Allow use as callback for stats updates."""
        self.on_progress_update(stats)
