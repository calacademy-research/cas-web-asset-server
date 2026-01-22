"""
ImageRecord - Record for a single image and its thumbnail status.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, Dict


@dataclass
class ThumbnailInfo:
    """
    Information about a single thumbnail at a specific scale.
    
    Attributes:
        scale: The max dimension (e.g., 200, 400)
        key: Full S3 key for this thumbnail
        size: Size in bytes
        modified: ISO timestamp
    """
    scale: int
    key: str
    size: int
    modified: str
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ThumbnailInfo':
        return cls(**data)


@dataclass
class ImageRecord:
    """
    Record for a single image and its thumbnail status.
    
    Attributes:
        original_key: S3 key for the original image
        original_size: Size of original in bytes
        original_modified: ISO timestamp of original
        base_thumbnail_key: S3 key for thumbnails (without _scale suffix)
        collection: Collection name
        filename: Base filename
        thumbnails: Dict mapping scale -> ThumbnailInfo for existing thumbnails
    """
    original_key: str
    original_size: int
    original_modified: str
    base_thumbnail_key: str
    collection: str
    filename: str
    thumbnails: Dict[int, ThumbnailInfo] = field(default_factory=dict)
    
    # Legacy field aliases for backwards compatibility during transition
    @property
    def thumbnail_key(self) -> str:
        """Legacy alias for base_thumbnail_key."""
        return self.base_thumbnail_key
    
    @property
    def thumbnail_exists(self) -> bool:
        """Legacy: True if ANY thumbnail exists."""
        return len(self.thumbnails) > 0
    
    @property
    def thumbnail_size(self) -> Optional[int]:
        """Legacy: Size of first thumbnail found, or None."""
        if self.thumbnails:
            first = next(iter(self.thumbnails.values()))
            return first.size
        return None
    
    @property
    def thumbnail_modified(self) -> Optional[str]:
        """Legacy: Modified time of first thumbnail found, or None."""
        if self.thumbnails:
            first = next(iter(self.thumbnails.values()))
            return first.modified
        return None
    
    def has_thumbnail(self, scale: Optional[int] = None) -> bool:
        """
        Check if a thumbnail exists.
        
        Args:
            scale: Specific scale to check, or None to check if ANY exists
        """
        if scale is not None:
            return scale in self.thumbnails
        return len(self.thumbnails) > 0
    
    def needs_thumbnail(self, scale: Optional[int] = None) -> bool:
        """
        Check if a thumbnail needs to be generated.
        
        Args:
            scale: Specific scale to check, or None to check if ANY is missing
        """
        if scale is not None:
            return scale not in self.thumbnails
        return len(self.thumbnails) == 0
    
    def get_thumbnail(self, scale: int) -> Optional[ThumbnailInfo]:
        """Get thumbnail info for a specific scale."""
        return self.thumbnails.get(scale)
    
    def add_thumbnail(self, info: ThumbnailInfo) -> None:
        """Add or update thumbnail info for a scale."""
        self.thumbnails[info.scale] = info
    
    def get_thumbnail_key(self, scale: int) -> str:
        """Get the S3 key for a thumbnail at a specific scale."""
        root, ext = self.base_thumbnail_key.rsplit('.', 1)
        return f"{root}_{scale}.{ext}"
    
    @property
    def available_scales(self) -> list:
        """Get list of available thumbnail scales."""
        return sorted(self.thumbnails.keys())
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'original_key': self.original_key,
            'original_size': self.original_size,
            'original_modified': self.original_modified,
            'base_thumbnail_key': self.base_thumbnail_key,
            'collection': self.collection,
            'filename': self.filename,
            'thumbnails': {
                str(scale): info.to_dict() 
                for scale, info in self.thumbnails.items()
            },
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ImageRecord':
        """Create from dictionary."""
        # Handle legacy format (thumbnail_key instead of base_thumbnail_key)
        base_key = data.get('base_thumbnail_key') or data.get('thumbnail_key', '')
        
        # Parse thumbnails
        thumbnails = {}
        if 'thumbnails' in data:
            for scale_str, info_data in data['thumbnails'].items():
                scale = int(scale_str)
                thumbnails[scale] = ThumbnailInfo.from_dict(info_data)
        elif data.get('thumbnail_exists'):
            # Legacy format: convert single thumbnail to new format
            # We don't know the scale, so assume 200
            thumbnails[200] = ThumbnailInfo(
                scale=200,
                key=base_key.replace('.', '_200.', 1) if '.' in base_key else f"{base_key}_200",
                size=data.get('thumbnail_size', 0),
                modified=data.get('thumbnail_modified', ''),
            )
        
        return cls(
            original_key=data['original_key'],
            original_size=data['original_size'],
            original_modified=data['original_modified'],
            base_thumbnail_key=base_key,
            collection=data['collection'],
            filename=data['filename'],
            thumbnails=thumbnails,
        )
    
    def format_status(self, scale: Optional[int] = None) -> str:
        """
        Format a human-readable status string for verbatim output.
        
        Args:
            scale: Specific scale to report on, or None for general status
            
        Returns:
            Status string like "filename.jpg - thumbnail EXISTS @200 (45.2 KB)"
        """
        if scale is not None:
            if scale in self.thumbnails:
                info = self.thumbnails[scale]
                size_str = self._format_bytes(info.size)
                return f"{self.filename} - thumbnail EXISTS @{scale} ({size_str})"
            else:
                return f"{self.filename} - thumbnail MISSING @{scale} (required)"
        
        # General status - report all thumbnails
        if self.thumbnails:
            scales = ', '.join(f"@{s}" for s in sorted(self.thumbnails.keys()))
            total_size = sum(t.size for t in self.thumbnails.values())
            size_str = self._format_bytes(total_size)
            return f"{self.filename} - thumbnails: {scales} ({size_str} total)"
        else:
            return f"{self.filename} - NO thumbnails"
    
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
