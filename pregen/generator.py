"""
Generator - Generates thumbnails based on a manifest.
"""

import logging
import os
import time
from typing import List, Optional, Iterator

from .s3_client import S3Client
from .thumbnail_generator import ThumbnailGenerator
from .manifest import Manifest
from .image_record import ImageRecord
from .generation_stats import GenerationStats
from .generation_progress import GenerationProgress


class Generator:
    """
    Generates thumbnails based on a manifest.
    
    Phase 2 of the two-phase thumbnail pre-generation process.
    """
    
    def __init__(
        self,
        s3_client: S3Client,
        thumbnail_generator: ThumbnailGenerator,
        cadence: float = 1.0,
        dry_run: bool = False,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize generator.
        
        Args:
            s3_client: S3 client instance
            thumbnail_generator: Thumbnail generator instance
            cadence: Seconds between processing each image
            dry_run: If True, don't actually generate thumbnails
            logger: Optional logger instance
        """
        self.s3 = s3_client
        self.thumb_gen = thumbnail_generator
        self.cadence = cadence
        self.dry_run = dry_run
        self.logger = logger or logging.getLogger(__name__)
        self.stats = GenerationStats()
        self._stop_requested = False
    
    def stop(self) -> None:
        """Request the generator to stop after current image."""
        self._stop_requested = True
    
    def generate_from_manifest(
        self,
        manifest: Manifest,
        collections: Optional[List[str]] = None,
        resume_from: Optional[str] = None,
        progress: Optional[GenerationProgress] = None,
        limit: Optional[int] = None
    ) -> GenerationStats:
        """
        Generate thumbnails for images in manifest.
        
        Args:
            manifest: Manifest with image records
            collections: Optional list of collections to process
            resume_from: Optional filename to resume from
            progress: Optional progress tracker
            limit: Optional limit on number of thumbnails to generate (for testing)
            
        Returns:
            GenerationStats with results
        """
        # Check for early stop before doing any work
        if self._stop_requested:
            self.logger.info("Stop was requested before generation started")
            self.stats = GenerationStats(total_to_process=0)
            return self.stats
        
        # Count records to process (with progress for large manifests)
        # But if we have a limit, we can stop early
        print("Counting records to process...")
        records_to_process = []
        count = 0
        for record in self._get_records_to_process(manifest, collections, resume_from):
            records_to_process.append(record)
            count += 1
            if count % 1000 == 0:
                print(f"  Found {count:,} records needing thumbnails...")
            # If we have a limit, only collect that many
            if limit and count >= limit:
                print(f"  Stopping at limit ({limit})")
                break
        
        if count >= 1000:
            print(f"  Total: {count:,} records to process")
        
        self.stats = GenerationStats(total_to_process=len(records_to_process))
        
        mode_str = " [DRY RUN]" if self.dry_run else ""
        limit_str = f" (limited to {limit})" if limit else ""
        self.logger.info(f"Starting generation: {len(records_to_process)} thumbnails to generate{mode_str}{limit_str}")
        
        for record in records_to_process:
            if self._stop_requested:
                self.logger.info("Stop requested, halting generation")
                break
            
            self._process_record(record, progress)
            
            if progress:
                progress.on_progress_update(self.stats)
            
            if self.cadence > 0 and not self.dry_run:
                time.sleep(self.cadence)
        
        self.logger.info(
            f"Generation complete: {self.stats.processed} generated, "
            f"{self.stats.skipped} skipped, {self.stats.errors} errors "
            f"({self.stats.elapsed_seconds:.1f}s)"
        )
        
        return self.stats
    
    def _get_records_to_process(
        self,
        manifest: Manifest,
        collections: Optional[List[str]],
        resume_from: Optional[str]
    ) -> Iterator[ImageRecord]:
        """Get records that need processing at the configured scale."""
        past_resume_point = resume_from is None
        target_scale = self.thumb_gen.size
        
        for record in manifest.records:
            if collections and record.collection not in collections:
                continue
            
            # Check if thumbnail exists at the target scale
            if record.has_thumbnail(target_scale):
                continue
            
            if not past_resume_point:
                if record.filename >= resume_from:
                    past_resume_point = True
                else:
                    continue
            
            yield record
    
    def _process_record(
        self, 
        record: ImageRecord, 
        progress: Optional[GenerationProgress]
    ) -> bool:
        """Process a single image record."""
        if self.dry_run:
            if progress:
                progress.on_dry_run(record)
            else:
                self.logger.info(f"[DRY RUN] Would generate: {record.filename}")
            self.stats.processed += 1
            return True
        
        try:
            self.logger.debug(f"Downloading: {record.original_key}")
            image_data = self.s3.download_object(record.original_key)
            
            ext = os.path.splitext(record.filename)[1]
            self.logger.debug(f"Generating thumbnail: {record.filename}")
            thumb_data, content_type = self.thumb_gen.generate(image_data, ext)
            
            # Generate thumbnail key with scale suffix
            thumb_key = record.get_thumbnail_key(self.thumb_gen.size)
            
            self.logger.debug(f"Uploading: {thumb_key}")
            self.s3.upload_object(thumb_key, thumb_data, content_type)
            
            self.stats.processed += 1
            self.stats.bytes_generated += len(thumb_data)
            
            if progress:
                progress.on_file_processed(record, success=True, thumb_size=len(thumb_data))
            else:
                self.logger.info(
                    f"Generated: {record.filename} ({len(thumb_data)} bytes) "
                    f"[{self.stats.processed}/{self.stats.total_to_process}]"
                )
            
            return True
            
        except Exception as e:
            error_msg = f"Error processing {record.filename}: {e}"
            self.logger.error(error_msg)
            self.stats.errors += 1
            self.stats.error_details.append(error_msg)
            
            if progress:
                progress.on_file_processed(record, success=False, error=str(e))
            
            return False
    
    def verify_thumbnail(self, record: ImageRecord, scale: Optional[int] = None) -> bool:
        """Verify a thumbnail exists and is valid at the given scale."""
        target_scale = scale or self.thumb_gen.size
        thumb_key = record.get_thumbnail_key(target_scale)
        metadata = self.s3.get_object_metadata(thumb_key)
        return metadata is not None and metadata.get('size', 0) > 0
