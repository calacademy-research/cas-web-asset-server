"""
CollectionStats - Statistics for a single collection.
"""

from dataclasses import dataclass, asdict


@dataclass
class CollectionStats:
    """
    Statistics for a single collection.
    
    Attributes:
        name: Collection name
        total_images: Total number of images
        with_thumbnails: Number with existing thumbnails
        missing_thumbnails: Number missing thumbnails
        total_original_bytes: Total size of originals
        total_thumbnail_bytes: Total size of existing thumbnails
    """
    name: str
    total_images: int = 0
    with_thumbnails: int = 0
    missing_thumbnails: int = 0
    total_original_bytes: int = 0
    total_thumbnail_bytes: int = 0
    
    @property
    def thumbnail_coverage(self) -> float:
        """Percentage of images with thumbnails."""
        if self.total_images == 0:
            return 100.0
        return (self.with_thumbnails / self.total_images) * 100
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'CollectionStats':
        """Create from dictionary."""
        return cls(**data)
