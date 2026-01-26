"""Tests for CollectionStats class."""

import pytest
from pregen.collection_stats import CollectionStats


class TestCollectionStats:
    """Tests for CollectionStats class."""
    
    def test_create_stats(self):
        """Test creating collection stats."""
        stats = CollectionStats(
            name='botany',
            total_images=100,
            with_thumbnails=75,
            missing_thumbnails=25,
        )
        
        assert stats.name == 'botany'
        assert stats.total_images == 100
    
    def test_thumbnail_coverage_full(self):
        """Test coverage calculation with all thumbnails."""
        stats = CollectionStats(
            name='test',
            total_images=100,
            with_thumbnails=100,
            missing_thumbnails=0,
        )
        
        assert stats.thumbnail_coverage == 100.0
    
    def test_thumbnail_coverage_partial(self):
        """Test coverage calculation with partial thumbnails."""
        stats = CollectionStats(
            name='test',
            total_images=100,
            with_thumbnails=75,
            missing_thumbnails=25,
        )
        
        assert stats.thumbnail_coverage == 75.0
    
    def test_thumbnail_coverage_empty(self):
        """Test coverage calculation with no images."""
        stats = CollectionStats(name='test', total_images=0)
        
        assert stats.thumbnail_coverage == 100.0
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        stats = CollectionStats(
            name='botany',
            total_images=100,
            with_thumbnails=75,
        )
        
        data = stats.to_dict()
        
        assert data['name'] == 'botany'
        assert data['total_images'] == 100
    
    def test_from_dict(self):
        """Test creation from dictionary."""
        data = {
            'name': 'test',
            'total_images': 50,
            'with_thumbnails': 25,
            'missing_thumbnails': 25,
            'total_original_bytes': 1000000,
            'total_thumbnail_bytes': 50000,
        }
        
        stats = CollectionStats.from_dict(data)
        
        assert stats.name == 'test'
        assert stats.total_images == 50
