"""
Thumbnail Pre-generation Package for cas-web-asset-server

Two-phase operation:
    1. Scan phase: Enumerate all images and existing thumbnails, save to manifest
    2. Generate phase: Read manifest and generate missing thumbnails

Supports both S3 and local filesystem storage.
"""

__version__ = "1.1.0"
__author__ = "California Academy of Sciences"

from .s3_config import S3Config
from .s3_client import S3Client
from .local_client import LocalConfig, LocalClient
from .thumbnail_generator import ThumbnailGenerator
from .image_record import ImageRecord, ThumbnailInfo
from .collection_stats import CollectionStats
from .manifest import Manifest
from .scanner_progress import ScannerProgress
from .scanner import Scanner
from .generation_stats import GenerationStats
from .generation_progress import GenerationProgress
from .generator import Generator
from .reporter import Reporter

__all__ = [
    "S3Config",
    "S3Client",
    "LocalConfig",
    "LocalClient",
    "ThumbnailGenerator",
    "ImageRecord",
    "ThumbnailInfo",
    "CollectionStats",
    "Manifest",
    "ScannerProgress",
    "Scanner",
    "GenerationStats",
    "GenerationProgress",
    "Generator",
    "Reporter",
]
