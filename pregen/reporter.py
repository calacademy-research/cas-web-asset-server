"""
Reporter - Generates human-readable reports from manifest data.
"""

import logging
import sys
from collections import defaultdict
from typing import Dict, List, Optional, TextIO, Set

from .manifest import Manifest


class Reporter:
    """
    Generates human-readable reports from manifest data.
    """
    
    def __init__(
        self,
        output: Optional[TextIO] = None,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize reporter.
        
        Args:
            output: Output stream (default: stdout)
            logger: Optional logger instance
        """
        self.output = output or sys.stdout
        self.logger = logger or logging.getLogger(__name__)
    
    def _print(self, text: str = "") -> None:
        """Print to output stream."""
        print(text, file=self.output)
    
    def _format_bytes(self, bytes_val: int) -> str:
        """Format bytes as human-readable string."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_val < 1024:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.1f} PB"
    
    def _format_duration(self, seconds: float) -> str:
        """Format duration as human-readable string."""
        if seconds < 60:
            return f"{seconds:.1f} seconds"
        elif seconds < 3600:
            return f"{seconds / 60:.1f} minutes"
        else:
            return f"{seconds / 3600:.1f} hours"
    
    def _print_storage_info(self, manifest: Manifest) -> None:
        """Print storage information from manifest."""
        storage_type = getattr(manifest, 'storage_type', 's3')
        
        if storage_type == 'local':
            local_root = getattr(manifest, 'local_root', 'unknown')
            self._print(f"  Storage:     Local filesystem")
            self._print(f"  Root:        {local_root}")
            self._print(f"  Prefix:      {manifest.s3_prefix}")
        else:
            self._print(f"  Storage:     S3")
            self._print(f"  Endpoint:    {manifest.s3_endpoint}")
            self._print(f"  Bucket:      {manifest.s3_bucket}/{manifest.s3_prefix}")
    
    def _analyze_thumbnail_sizes(self, manifest: Manifest, collections: Optional[List[str]] = None) -> dict:
        """
        Analyze manifest to get thumbnail size statistics.
        
        Returns:
            Dict with structure:
            {
                'all_scales': set of all scales found,
                'by_collection': {
                    collection_name: {
                        'total_images': int,
                        'with_any_thumb': int,
                        'without_any_thumb': int,
                        'by_scale': {
                            scale: {'count': int, 'total_bytes': int}
                        }
                    }
                },
                'totals': {
                    'total_images': int,
                    'with_any_thumb': int,
                    'without_any_thumb': int,
                    'by_scale': { scale: {'count': int, 'total_bytes': int} }
                }
            }
        """
        all_scales: Set[int] = set()
        by_collection: Dict[str, dict] = {}
        
        total_records = len(manifest.records)
        if total_records >= 1000:
            print(f"Analyzing {total_records:,} records...")
        
        for i, record in enumerate(manifest.records):
            if (i + 1) % 1000 == 0 and total_records >= 1000:
                print(f"  Analyzed {i + 1:,} / {total_records:,} records...")
            
            coll = record.collection
            if collections and coll not in collections:
                continue
            
            # Initialize collection stats if needed
            if coll not in by_collection:
                by_collection[coll] = {
                    'total_images': 0,
                    'with_any_thumb': 0,
                    'without_any_thumb': 0,
                    'by_scale': defaultdict(lambda: {'count': 0, 'total_bytes': 0}),
                }
            
            stats = by_collection[coll]
            stats['total_images'] += 1
            
            if record.thumbnails:
                stats['with_any_thumb'] += 1
                for scale, thumb_info in record.thumbnails.items():
                    all_scales.add(scale)
                    stats['by_scale'][scale]['count'] += 1
                    stats['by_scale'][scale]['total_bytes'] += thumb_info.size
            else:
                stats['without_any_thumb'] += 1
        
        # Calculate totals
        totals = {
            'total_images': 0,
            'with_any_thumb': 0,
            'without_any_thumb': 0,
            'by_scale': defaultdict(lambda: {'count': 0, 'total_bytes': 0}),
        }
        
        for coll_stats in by_collection.values():
            totals['total_images'] += coll_stats['total_images']
            totals['with_any_thumb'] += coll_stats['with_any_thumb']
            totals['without_any_thumb'] += coll_stats['without_any_thumb']
            for scale, scale_stats in coll_stats['by_scale'].items():
                totals['by_scale'][scale]['count'] += scale_stats['count']
                totals['by_scale'][scale]['total_bytes'] += scale_stats['total_bytes']
        
        return {
            'all_scales': all_scales,
            'by_collection': by_collection,
            'totals': totals,
        }
    
    def report_thumbnail_sizes(
        self, 
        manifest: Manifest, 
        collections: Optional[List[str]] = None,
        target_scale: Optional[int] = None
    ) -> None:
        """
        Generate a detailed report of thumbnail sizes per collection.
        
        Args:
            manifest: The manifest to report on
            collections: Optional list of collections to include
            target_scale: Optional specific scale to highlight (e.g., 200)
        """
        self._print("=" * 80)
        self._print("THUMBNAIL SIZE ANALYSIS REPORT")
        self._print("=" * 80)
        self._print()
        
        self._print("Manifest Information:")
        self._print(f"  Created:     {manifest.created_at}")
        self._print_storage_info(manifest)
        self._print()
        
        # Analyze the manifest
        analysis = self._analyze_thumbnail_sizes(manifest, collections)
        all_scales = sorted(analysis['all_scales'])
        by_collection = analysis['by_collection']
        totals = analysis['totals']
        
        if not all_scales:
            self._print("No thumbnail scales found in manifest.")
            self._print()
            return
        
        self._print(f"Thumbnail scales found: {', '.join(f'@{s}' for s in all_scales)}")
        if target_scale:
            self._print(f"Target scale for generation: @{target_scale}")
        self._print()
        
        # Per-collection breakdown
        for coll_name in sorted(by_collection.keys()):
            coll_stats = by_collection[coll_name]
            self._print("-" * 80)
            self._print(f"COLLECTION: {coll_name}")
            self._print("-" * 80)
            self._print()
            
            total = coll_stats['total_images']
            with_thumb = coll_stats['with_any_thumb']
            without_thumb = coll_stats['without_any_thumb']
            coverage = (with_thumb / total * 100) if total > 0 else 0
            
            self._print(f"  Total Images:              {total:>12,}")
            self._print(f"  With Any Thumbnail:        {with_thumb:>12,}  ({coverage:.1f}%)")
            self._print(f"  Without Any Thumbnail:     {without_thumb:>12,}  ({100-coverage:.1f}%)")
            self._print()
            
            self._print("  Thumbnail Sizes:")
            self._print(f"    {'Scale':<10} {'Count':>12} {'Coverage':>10} {'Total Size':>14} {'Avg Size':>12}")
            self._print(f"    {'-'*10} {'-'*12} {'-'*10} {'-'*14} {'-'*12}")
            
            for scale in all_scales:
                scale_stats = coll_stats['by_scale'].get(scale, {'count': 0, 'total_bytes': 0})
                count = scale_stats['count']
                total_bytes = scale_stats['total_bytes']
                scale_coverage = (count / total * 100) if total > 0 else 0
                avg_bytes = total_bytes // count if count > 0 else 0
                
                marker = " <--" if target_scale and scale == target_scale else ""
                missing = total - count
                
                self._print(
                    f"    @{scale:<9} {count:>12,} {scale_coverage:>9.1f}% "
                    f"{self._format_bytes(total_bytes):>14} {self._format_bytes(avg_bytes):>12}{marker}"
                )
            
            self._print()
            
            # Show what's missing for target scale
            if target_scale:
                target_count = coll_stats['by_scale'].get(target_scale, {'count': 0})['count']
                missing = total - target_count
                if missing > 0:
                    self._print(f"  ⚠️  Missing @{target_scale} thumbnails: {missing:,}")
                else:
                    self._print(f"  ✓  All images have @{target_scale} thumbnails")
                self._print()
        
        # Overall totals
        self._print("=" * 80)
        self._print("OVERALL TOTALS")
        self._print("=" * 80)
        self._print()
        
        total = totals['total_images']
        with_thumb = totals['with_any_thumb']
        without_thumb = totals['without_any_thumb']
        coverage = (with_thumb / total * 100) if total > 0 else 0
        
        self._print(f"  Total Images:              {total:>12,}")
        self._print(f"  With Any Thumbnail:        {with_thumb:>12,}  ({coverage:.1f}%)")
        self._print(f"  Without Any Thumbnail:     {without_thumb:>12,}  ({100-coverage:.1f}%)")
        self._print()
        
        self._print("  All Thumbnail Sizes:")
        self._print(f"    {'Scale':<10} {'Count':>12} {'Coverage':>10} {'Total Size':>14} {'Avg Size':>12}")
        self._print(f"    {'-'*10} {'-'*12} {'-'*10} {'-'*14} {'-'*12}")
        
        for scale in all_scales:
            scale_stats = totals['by_scale'].get(scale, {'count': 0, 'total_bytes': 0})
            count = scale_stats['count']
            total_bytes = scale_stats['total_bytes']
            scale_coverage = (count / total * 100) if total > 0 else 0
            avg_bytes = total_bytes // count if count > 0 else 0
            
            marker = " <--" if target_scale and scale == target_scale else ""
            
            self._print(
                f"    @{scale:<9} {count:>12,} {scale_coverage:>9.1f}% "
                f"{self._format_bytes(total_bytes):>14} {self._format_bytes(avg_bytes):>12}{marker}"
            )
        
        self._print()
        
        if target_scale:
            target_count = totals['by_scale'].get(target_scale, {'count': 0})['count']
            missing = total - target_count
            self._print(f"  To generate @{target_scale} thumbnails: {missing:,}")
        self._print()
    
    def report_summary(self, manifest: Manifest) -> None:
        """Generate a summary report."""
        self._print("=" * 70)
        self._print("THUMBNAIL PRE-GENERATION MANIFEST SUMMARY")
        self._print("=" * 70)
        self._print()
        
        self._print("Manifest Information:")
        self._print(f"  Created:     {manifest.created_at}")
        self._print(f"  Age:         {manifest.age_hours:.1f} hours")
        self._print_storage_info(manifest)
        self._print(f"  Scan Time:   {self._format_duration(manifest.scan_duration_seconds)}")
        self._print()
        
        if manifest.is_stale():
            self._print("⚠️  WARNING: Manifest is older than 24 hours!")
            self._print("   Consider re-running scan to get current data.")
            self._print()
        
        self._print("Overall Statistics:")
        self._print(f"  Total Images:         {manifest.total_images:,}")
        self._print(f"  With Thumbnails:      {manifest.total_with_thumbnails:,}")
        self._print(f"  Missing Thumbnails:   {manifest.total_missing_thumbnails:,}")
        
        if manifest.total_images > 0:
            coverage = (manifest.total_with_thumbnails / manifest.total_images) * 100
            self._print(f"  Coverage:             {coverage:.1f}%")
        self._print()
        
        self._print("Collections:")
        self._print("-" * 70)
        self._print(f"{'Collection':<20} {'Total':>10} {'Has Thumb':>12} {'Missing':>10} {'Coverage':>10}")
        self._print("-" * 70)
        
        for name in sorted(manifest.collection_stats.keys()):
            stats = manifest.collection_stats[name]
            self._print(
                f"{name:<20} {stats.total_images:>10,} "
                f"{stats.with_thumbnails:>12,} {stats.missing_thumbnails:>10,} "
                f"{stats.thumbnail_coverage:>9.1f}%"
            )
        
        self._print("-" * 70)
        self._print()
    
    def report_detailed(self, manifest: Manifest) -> None:
        """Generate a detailed report including size information."""
        self.report_summary(manifest)
        
        self._print("Storage Statistics:")
        self._print("-" * 70)
        self._print(f"{'Collection':<20} {'Original Size':>15} {'Thumb Size':>15} {'Ratio':>10}")
        self._print("-" * 70)
        
        total_original = 0
        total_thumb = 0
        
        for name in sorted(manifest.collection_stats.keys()):
            stats = manifest.collection_stats[name]
            total_original += stats.total_original_bytes
            total_thumb += stats.total_thumbnail_bytes
            
            ratio = ""
            if stats.total_original_bytes > 0 and stats.total_thumbnail_bytes > 0:
                ratio = f"{stats.total_thumbnail_bytes / stats.total_original_bytes * 100:.1f}%"
            
            self._print(
                f"{name:<20} "
                f"{self._format_bytes(stats.total_original_bytes):>15} "
                f"{self._format_bytes(stats.total_thumbnail_bytes):>15} "
                f"{ratio:>10}"
            )
        
        self._print("-" * 70)
        
        total_ratio = ""
        if total_original > 0 and total_thumb > 0:
            total_ratio = f"{total_thumb / total_original * 100:.1f}%"
        
        self._print(
            f"{'TOTAL':<20} "
            f"{self._format_bytes(total_original):>15} "
            f"{self._format_bytes(total_thumb):>15} "
            f"{total_ratio:>10}"
        )
        self._print()
    
    def report_action_plan(
        self,
        manifest: Manifest,
        size: int = 200,
        cadence: float = 1.0,
        collections: Optional[List[str]] = None
    ) -> None:
        """Generate a report showing what actions would be taken."""
        self._print("=" * 70)
        self._print("THUMBNAIL GENERATION ACTION PLAN")
        self._print("=" * 70)
        self._print()
        
        if manifest.is_stale():
            self._print("⚠️  WARNING: Manifest is older than 24 hours!")
            self._print("   The following plan may not reflect current state.")
            self._print("   Consider re-running scan first.")
            self._print()
        
        self._print("Generation Parameters:")
        self._print(f"  Thumbnail Size: {size}px")
        self._print(f"  Cadence:        {cadence}s between images")
        if collections:
            self._print(f"  Collections:    {', '.join(collections)}")
        else:
            self._print(f"  Collections:    All ({len(manifest.collections)})")
        self._print()
        
        to_generate = 0
        by_collection = {}
        
        total_records = len(manifest.records)
        if total_records >= 1000:
            print(f"Scanning {total_records:,} records for action plan...")
        
        for i, record in enumerate(manifest.records):
            if (i + 1) % 1000 == 0 and total_records >= 1000:
                print(f"  Scanned {i + 1:,} / {total_records:,} records...")
            
            if collections and record.collection not in collections:
                continue
            if not record.thumbnail_exists:
                to_generate += 1
                by_collection[record.collection] = by_collection.get(record.collection, 0) + 1
        
        self._print("Work Summary:")
        self._print(f"  Thumbnails to Generate: {to_generate:,}")
        self._print()
        
        if to_generate == 0:
            self._print("✓ All images already have thumbnails!")
            return
        
        self._print("By Collection:")
        self._print("-" * 50)
        self._print(f"{'Collection':<25} {'To Generate':>15}")
        self._print("-" * 50)
        
        for name in sorted(by_collection.keys()):
            count = by_collection[name]
            self._print(f"{name:<25} {count:>15,}")
        
        self._print("-" * 50)
        self._print(f"{'TOTAL':<25} {to_generate:>15,}")
        self._print()
        
        if cadence > 0:
            estimated_seconds = to_generate * cadence
            self._print("Time Estimate:")
            self._print(f"  At {cadence}s cadence: {self._format_duration(estimated_seconds)}")
            
            if cadence != 0.5:
                self._print(f"  At 0.5s cadence: {self._format_duration(to_generate * 0.5)}")
            if cadence != 0.1:
                self._print(f"  At 0.1s cadence: {self._format_duration(to_generate * 0.1)}")
        self._print()
    
    def report_missing_files(
        self,
        manifest: Manifest,
        collections: Optional[List[str]] = None,
        limit: int = 100
    ) -> None:
        """List files that are missing thumbnails."""
        self._print("=" * 70)
        self._print("FILES MISSING THUMBNAILS")
        self._print("=" * 70)
        self._print()
        
        total_records = len(manifest.records)
        if total_records >= 1000 and limit > 100:
            print(f"Scanning {total_records:,} records for missing thumbnails...")
        
        count = 0
        scanned = 0
        for record in manifest.records:
            scanned += 1
            if scanned % 1000 == 0 and total_records >= 1000 and limit > 100:
                print(f"  Scanned {scanned:,} / {total_records:,} records, found {count:,} missing...")
            
            if collections and record.collection not in collections:
                continue
            if not record.thumbnail_exists:
                self._print(f"  [{record.collection}] {record.filename}")
                count += 1
                if count >= limit:
                    remaining = manifest.total_missing_thumbnails - count
                    if remaining > 0:
                        self._print(f"  ... and {remaining:,} more")
                    break
        
        self._print()
        self._print(f"Total missing: {manifest.total_missing_thumbnails:,}")
        self._print()
