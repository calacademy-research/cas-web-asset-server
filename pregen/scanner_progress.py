"""
ScannerProgress - Tracks and displays scan progress.
"""

import logging
import time
from typing import Dict, Optional

from .image_record import ImageRecord


class ScannerProgress:
    """
    Tracks and displays scan progress with optional per-file output.
    """
    
    def __init__(
        self,
        show_files: bool = False,
        log_interval: int = 500,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize progress tracker.
        
        Args:
            show_files: If True, print each file as it's scanned
            log_interval: Log summary progress every N images (when not show_files)
            logger: Optional logger instance
        """
        self.show_files = show_files
        self.log_interval = log_interval
        self.logger = logger or logging.getLogger(__name__)
        self.collection_counts: Dict[str, int] = {}
        self.start_time: Optional[float] = None  # Set when originals scan starts
    
    def on_file_scanned(self, record: ImageRecord) -> None:
        """
        Called when a file is scanned.
        
        Args:
            record: The scanned image record
        """
        # Start timer on first file
        if self.start_time is None:
            self.start_time = time.time()
        
        # Update counts
        self.collection_counts[record.collection] = \
            self.collection_counts.get(record.collection, 0) + 1
        
        count = self.collection_counts[record.collection]
        total = sum(self.collection_counts.values())
        
        if self.show_files:
            # Print each file with its status
            status = record.format_status()
            print(f"  [{record.collection}] {status}")
        elif count % self.log_interval == 0:
            # Periodic summary
            elapsed = time.time() - self.start_time
            rate = total / elapsed if elapsed > 0 else 0
            self.logger.info(
                f"  Progress: {count} in {record.collection} "
                f"(total: {total:,}, {rate:.0f}/sec)"
            )
    
    def on_collection_start(self, collection: str) -> None:
        """Called when starting to scan a collection."""
        if self.show_files:
            print(f"\n=== Scanning collection: {collection} ===")
        else:
            self.logger.info(f"Scanning collection: {collection}")
    
    def on_collection_complete(
        self, 
        collection: str, 
        total: int, 
        with_thumbs: int, 
        missing: int
    ) -> None:
        """Called when a collection scan is complete."""
        if self.show_files:
            print(f"--- {collection}: {total} images, {with_thumbs} with thumbnails, {missing} missing ---")
        else:
            self.logger.info(
                f"  Collection {collection}: {total} images, "
                f"{with_thumbs} with thumbnails, {missing} missing"
            )
    
    def on_thumbnails_loaded(self, collection: str, count: int) -> None:
        """Called when existing thumbnails are loaded for a collection."""
        if self.show_files:
            print(f"  Loaded {count:,} existing thumbnails for {collection}")
        else:
            self.logger.info(f"  Found {count:,} existing thumbnails")
    
    def __call__(self, record: ImageRecord) -> None:
        """Allow use as callback."""
        self.on_file_scanned(record)
