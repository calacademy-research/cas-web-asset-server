"""
Manifest - Complete scan manifest containing all image records and metadata.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Iterator

from .image_record import ImageRecord
from .collection_stats import CollectionStats


@dataclass
class Manifest:
    """
    Complete scan manifest containing all image records and metadata.
    
    Attributes:
        created_at: ISO timestamp when manifest was created
        s3_endpoint: S3 endpoint used for scan (None for local)
        s3_bucket: S3 bucket scanned (None for local)
        s3_prefix: Prefix within storage (e.g., 'attachments')
        storage_type: 'local' or 's3'
        local_root: Root path for local storage (None for S3)
        collections: List of collection names
        collection_stats: Statistics per collection
        records: List of all image records
        scan_duration_seconds: How long the scan took
    """
    created_at: str
    s3_endpoint: Optional[str]
    s3_bucket: Optional[str]
    s3_prefix: str
    collections: List[str] = field(default_factory=list)
    collection_stats: Dict[str, CollectionStats] = field(default_factory=dict)
    records: List[ImageRecord] = field(default_factory=list)
    scan_duration_seconds: float = 0.0
    storage_type: str = 's3'
    local_root: Optional[str] = None
    
    AGE_WARNING_HOURS = 24
    
    def add_record(self, record: ImageRecord) -> None:
        """Add an image record to the manifest."""
        self.records.append(record)
        
        if record.collection not in self.collection_stats:
            self.collection_stats[record.collection] = CollectionStats(name=record.collection)
        
        stats = self.collection_stats[record.collection]
        stats.total_images += 1
        stats.total_original_bytes += record.original_size
        
        if record.thumbnail_exists:
            stats.with_thumbnails += 1
            # Sum all thumbnail sizes
            total_thumb_bytes = sum(t.size for t in record.thumbnails.values())
            stats.total_thumbnail_bytes += total_thumb_bytes
        else:
            stats.missing_thumbnails += 1
    
    def get_records_needing_thumbnails(self) -> Iterator[ImageRecord]:
        """Yield records that need thumbnails generated."""
        count = 0
        for record in self.records:
            if record.needs_thumbnail():
                count += 1
                yield record
    
    def get_records_for_collection(self, collection: str) -> Iterator[ImageRecord]:
        """Yield records for a specific collection."""
        for record in self.records:
            if record.collection == collection:
                yield record
    
    @property
    def total_images(self) -> int:
        """Total number of images across all collections."""
        return len(self.records)
    
    @property
    def total_with_thumbnails(self) -> int:
        """Total images with existing thumbnails."""
        return sum(1 for r in self.records if r.thumbnail_exists)
    
    @property
    def total_missing_thumbnails(self) -> int:
        """Total images missing thumbnails."""
        return sum(1 for r in self.records if not r.thumbnail_exists)
    
    @property
    def age_hours(self) -> float:
        """Age of manifest in hours."""
        created = datetime.fromisoformat(self.created_at)
        now = datetime.now()
        return (now - created).total_seconds() / 3600
    
    def is_stale(self, threshold_hours: Optional[float] = None) -> bool:
        """Check if manifest is older than threshold."""
        threshold = threshold_hours or self.AGE_WARNING_HOURS
        return self.age_hours > threshold
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        print(f"Serializing manifest with {len(self.records):,} records...")
        
        records_list = []
        for i, r in enumerate(self.records):
            if (i + 1) % 1000 == 0:
                print(f"  Serialized {i + 1:,} / {len(self.records):,} records...")
            records_list.append(r.to_dict())
        
        print(f"  Serialization complete: {len(records_list):,} records")
        
        return {
            'created_at': self.created_at,
            'storage_type': self.storage_type,
            's3_endpoint': self.s3_endpoint,
            's3_bucket': self.s3_bucket,
            's3_prefix': self.s3_prefix,
            'local_root': self.local_root,
            'collections': self.collections,
            'collection_stats': {
                name: stats.to_dict() 
                for name, stats in self.collection_stats.items()
            },
            'records': records_list,
            'scan_duration_seconds': self.scan_duration_seconds,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Manifest':
        """Create from dictionary."""
        manifest = cls(
            created_at=data['created_at'],
            s3_endpoint=data.get('s3_endpoint'),
            s3_bucket=data.get('s3_bucket'),
            s3_prefix=data.get('s3_prefix', 'attachments'),
            collections=data.get('collections', []),
            scan_duration_seconds=data.get('scan_duration_seconds', 0.0),
            storage_type=data.get('storage_type', 's3'),
            local_root=data.get('local_root'),
        )
        
        for name, stats_data in data.get('collection_stats', {}).items():
            manifest.collection_stats[name] = CollectionStats.from_dict(stats_data)
        
        records_data = data.get('records', [])
        total_records = len(records_data)
        if total_records > 0:
            print(f"Loading {total_records:,} records from manifest...")
        
        for i, record_data in enumerate(records_data):
            if (i + 1) % 1000 == 0:
                print(f"  Loaded {i + 1:,} / {total_records:,} records...")
            manifest.records.append(ImageRecord.from_dict(record_data))
        
        if total_records >= 1000:
            print(f"  Load complete: {total_records:,} records")
        
        return manifest
    
    def save(self, filepath: str) -> None:
        """Save manifest to JSON file."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        print(f"Saving manifest to {filepath}...")
        data = self.to_dict()
        
        print(f"Writing JSON file...")
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        
        size_mb = path.stat().st_size / (1024 * 1024)
        print(f"Manifest saved: {size_mb:.1f} MB")
    
    @classmethod
    def load(cls, filepath: str) -> 'Manifest':
        """Load manifest from JSON file."""
        path = Path(filepath)
        size_mb = path.stat().st_size / (1024 * 1024)
        print(f"Loading manifest from {filepath} ({size_mb:.1f} MB)...")
        
        print(f"Parsing JSON...")
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        print(f"Building manifest...")
        return cls.from_dict(data)
    
    @classmethod
    def create_new(
        cls, 
        s3_endpoint: Optional[str] = None, 
        s3_bucket: Optional[str] = None, 
        s3_prefix: str = 'attachments',
        storage_type: str = 's3',
        local_root: Optional[str] = None
    ) -> 'Manifest':
        """Create a new empty manifest."""
        return cls(
            created_at=datetime.now().isoformat(),
            s3_endpoint=s3_endpoint,
            s3_bucket=s3_bucket,
            s3_prefix=s3_prefix,
            storage_type=storage_type,
            local_root=local_root,
        )
