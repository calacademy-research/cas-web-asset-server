"""
Scanner - Scans storage to enumerate all images and their thumbnail status.
"""

import logging
import os
import re
import time
from typing import Dict, List, Optional, Union

from .s3_client import S3Client
from .local_client import LocalClient
from .manifest import Manifest
from .image_record import ImageRecord, ThumbnailInfo
from .scanner_progress import ScannerProgress

# Type alias for storage clients
StorageClient = Union[S3Client, LocalClient]


class Scanner:
    """
    Scans storage and produces a manifest of images and thumbnails.
    
    Works with both S3 (S3Client) and local filesystem (LocalClient).
    Phase 1 of the two-phase thumbnail pre-generation process.
    """
    
    # Pattern to match thumbnail filenames: uuid_scale.ext
    # Captures: (uuid, scale, ext)
    THUMB_PATTERN = re.compile(r'^(.+)_(\d+)(\.[^.]+)$')
    
    def __init__(
        self,
        storage_client: StorageClient,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize scanner.
        
        Args:
            storage_client: Storage client instance (S3Client or LocalClient)
            logger: Optional logger instance
        """
        self.s3 = storage_client  # Named s3 for backwards compat, works with any client
        self.logger = logger or logging.getLogger(__name__)
    
    def scan(
        self,
        collections: Optional[List[str]] = None,
        progress: Optional[ScannerProgress] = None,
        limit: Optional[int] = None
    ) -> Manifest:
        """
        Scan S3 storage and create a manifest.
        
        Args:
            collections: Optional list of collections to scan (None = all)
            progress: Optional progress tracker for callbacks
            limit: Optional limit on number of images to scan (for testing)
            
        Returns:
            Manifest containing all image records
        """
        start_time = time.time()
        
        # Detect storage type from client
        is_local = hasattr(self.s3, 'config') and hasattr(self.s3.config, 'root_path')
        
        if is_local:
            manifest = Manifest.create_new(
                s3_prefix=self.s3.config.prefix,
                storage_type='local',
                local_root=self.s3.config.root_path,
            )
        else:
            manifest = Manifest.create_new(
                s3_endpoint=self.s3.config.endpoint,
                s3_bucket=self.s3.config.bucket,
                s3_prefix=self.s3.config.prefix,
                storage_type='s3',
            )
        
        if collections:
            target_collections = collections
        else:
            self.logger.info("Discovering collections...")
            target_collections = self.s3.list_collections()
            
        manifest.collections = target_collections
        self.logger.info(f"Collections to scan: {target_collections}")
        
        if limit:
            self.logger.info(f"Limit: {limit} images (testing mode)")
        
        total_scanned = 0
        limit_reached = False
        
        for collection in target_collections:
            if limit_reached:
                break
            scanned = self._scan_collection(
                manifest, collection, progress, 
                limit=limit, 
                already_scanned=total_scanned
            )
            total_scanned += scanned
            if limit and total_scanned >= limit:
                limit_reached = True
                self.logger.info(f"Limit of {limit} reached, stopping scan")
        
        manifest.scan_duration_seconds = time.time() - start_time
        
        self.logger.info(
            f"Scan complete: {manifest.total_images} images, "
            f"{manifest.total_with_thumbnails} with thumbnails, "
            f"{manifest.total_missing_thumbnails} missing thumbnails "
            f"({manifest.scan_duration_seconds:.1f}s)"
        )
        
        return manifest
    
    @classmethod
    def normalize_thumbnail_key(cls, thumb_key: str) -> Optional[str]:
        """
        Normalize a thumbnail key by removing the scale suffix.
        
        Converts: .../thumbnails/.../uuid_200.jpg -> .../thumbnails/.../uuid.jpg
        
        Args:
            thumb_key: The actual thumbnail S3 key (with _scale suffix)
            
        Returns:
            Normalized key (without scale suffix), or None if not a valid thumbnail
        """
        dirname = os.path.dirname(thumb_key)
        filename = os.path.basename(thumb_key)
        
        match = cls.THUMB_PATTERN.match(filename)
        if match:
            uuid_part, scale, ext = match.groups()
            normalized_filename = f"{uuid_part}{ext}"
            return os.path.join(dirname, normalized_filename)
        
        # Not a scaled thumbnail, return as-is
        return thumb_key
    
    @classmethod
    def extract_thumbnail_info(cls, thumb_key: str) -> Optional[dict]:
        """
        Extract info from a thumbnail key.
        
        Args:
            thumb_key: The thumbnail S3 key
            
        Returns:
            Dict with 'normalized_key', 'scale', or None if not valid
        """
        dirname = os.path.dirname(thumb_key)
        filename = os.path.basename(thumb_key)
        
        match = cls.THUMB_PATTERN.match(filename)
        if match:
            uuid_part, scale, ext = match.groups()
            normalized_filename = f"{uuid_part}{ext}"
            return {
                'normalized_key': os.path.join(dirname, normalized_filename),
                'scale': int(scale),
                'original_key': thumb_key,
            }
        
        return None
    
    def _scan_collection(
        self,
        manifest: Manifest,
        collection: str,
        progress: Optional[ScannerProgress] = None,
        limit: Optional[int] = None,
        already_scanned: int = 0
    ) -> int:
        """
        Scan a single collection.
        
        Args:
            manifest: Manifest to populate
            collection: Collection name
            progress: Optional progress tracker
            limit: Optional limit on total images to scan
            already_scanned: Number of images already scanned in previous collections
            
        Returns:
            Number of images scanned in this collection
        """
        if progress:
            progress.on_collection_start(collection)
        else:
            self.logger.info(f"Scanning collection: {collection}")
        
        # For small limits, use on-demand thumbnail checking instead of full index
        # This avoids scanning millions of thumbnails for a quick test
        use_ondemand = limit is not None and limit <= 100
        
        if use_ondemand:
            self.logger.info(f"  Using on-demand thumbnail checking (limit={limit})")
            existing_thumbnails = {}  # Empty - will check on-demand
        else:
            # Build index of existing thumbnails (keyed by normalized path)
            self.logger.info(f"  Loading existing thumbnails...")
            existing_thumbnails = self._load_thumbnail_index(collection)
            
            # Count unique originals that have at least one thumbnail
            originals_with_thumbs = len(existing_thumbnails)
            # Count total thumbnail files
            total_thumb_files = sum(len(scales) for scales in existing_thumbnails.values())
            
            if progress:
                progress.on_thumbnails_loaded(collection, total_thumb_files)
            else:
                self.logger.info(f"  Found {total_thumb_files} thumbnails for {originals_with_thumbs} originals")
        
        # Scan originals
        count = 0
        for original in self.s3.list_originals(collection):
            # Check limit
            if limit and (already_scanned + count) >= limit:
                self.logger.info(f"  Stopping at limit ({limit})")
                break
            
            original_key = original['key']
            base_thumbnail_key = self.s3.get_thumbnail_key(original_key)
            filename = os.path.basename(original_key)
            
            # Create record with empty thumbnails dict
            record = ImageRecord(
                original_key=original_key,
                original_size=original['size'],
                original_modified=original['last_modified'],
                base_thumbnail_key=base_thumbnail_key,
                collection=collection,
                filename=filename,
            )
            
            # Populate thumbnails
            if use_ondemand:
                # Check for thumbnails on-demand
                self._populate_thumbnails_ondemand(record)
            else:
                # Look up from pre-built index
                thumb_scales = existing_thumbnails.get(base_thumbnail_key, {})
                for scale, info in thumb_scales.items():
                    record.add_thumbnail(ThumbnailInfo(
                        scale=scale,
                        key=info['key'],
                        size=info['size'],
                        modified=info['last_modified'],
                    ))
            
            manifest.add_record(record)
            count += 1
            
            if progress:
                progress.on_file_scanned(record)
            elif count % 1000 == 0:
                self.logger.info(f"  Scanned {count} images in {collection}...")
        
        stats = manifest.collection_stats.get(collection)
        if progress and stats:
            progress.on_collection_complete(
                collection, 
                stats.total_images, 
                stats.with_thumbnails, 
                stats.missing_thumbnails
            )
        elif stats:
            self.logger.info(
                f"  Collection {collection}: {stats.total_images} images, "
                f"{stats.with_thumbnails} with thumbnails"
            )
        
        return count
    
    def _load_thumbnail_index(self, collection: str) -> Dict[str, Dict[int, dict]]:
        """
        Load an index of all existing thumbnails for a collection.
        
        The index is keyed by NORMALIZED thumbnail path (without _scale suffix),
        then by scale, so multiple thumbnail sizes per original are tracked.
        
        Args:
            collection: Collection name
            
        Returns:
            Dict mapping normalized_key -> { scale -> { 'key', 'size', 'last_modified' } }
        """
        index: Dict[str, Dict[int, dict]] = {}
        
        for thumb in self.s3.list_thumbnails(collection):
            actual_key = thumb['key']
            
            # Extract info from the key
            info = self.extract_thumbnail_info(actual_key)
            if info:
                normalized_key = info['normalized_key']
                scale = info['scale']
                
                # Initialize dict for this original if needed
                if normalized_key not in index:
                    index[normalized_key] = {}
                
                # Store this scale
                index[normalized_key][scale] = {
                    'key': actual_key,
                    'size': thumb['size'],
                    'last_modified': thumb['last_modified'],
                }
            else:
                # Non-scaled thumbnail (legacy?) - treat as scale 0
                if actual_key not in index:
                    index[actual_key] = {}
                index[actual_key][0] = {
                    'key': actual_key,
                    'size': thumb['size'],
                    'last_modified': thumb['last_modified'],
                }
        
        return index
    
    def _populate_thumbnails_ondemand(self, record: ImageRecord) -> None:
        """
        Check for existing thumbnails on-demand and populate the record.
        
        Uses a prefix listing to find ALL thumbnail sizes for this image.
        Works with both S3 and local storage.
        
        Args:
            record: ImageRecord to populate with found thumbnails
        """
        # Get the prefix for this image's thumbnails
        # e.g., attachments/botany/thumbnails/00/00/uuid
        root, ext = os.path.splitext(record.base_thumbnail_key)
        prefix = f"{root}_"
        
        # Check if this is a local client (has list_prefix method)
        if hasattr(self.s3, 'list_prefix'):
            # Local storage
            try:
                results = self.s3.list_prefix(prefix, max_keys=100)
                for obj in results:
                    key = obj['key']
                    info = self.extract_thumbnail_info(key)
                    if info:
                        record.add_thumbnail(ThumbnailInfo(
                            scale=info['scale'],
                            key=key,
                            size=obj['size'],
                            modified=obj['last_modified'],
                        ))
            except Exception as e:
                self.logger.warning(f"Error listing thumbnails for {record.filename}: {e}")
        else:
            # S3 storage
            try:
                response = self.s3.client.list_objects_v2(
                    Bucket=self.s3.config.bucket,
                    Prefix=prefix,
                    MaxKeys=100  # Unlikely to have more than 100 sizes
                )
                
                for obj in response.get('Contents', []):
                    key = obj['Key']
                    info = self.extract_thumbnail_info(key)
                    if info:
                        record.add_thumbnail(ThumbnailInfo(
                            scale=info['scale'],
                            key=key,
                            size=obj['Size'],
                            modified=obj['LastModified'].isoformat(),
                        ))
            except Exception as e:
                self.logger.warning(f"Error listing thumbnails for {record.filename}: {e}")
