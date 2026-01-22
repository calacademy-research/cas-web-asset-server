"""Tests for Manifest class."""

import os
import tempfile
import pytest

from pregen.manifest import Manifest
from pregen.image_record import ImageRecord


class TestManifest:
    """Tests for Manifest class."""
    
    def test_create_new(self):
        """Test creating a new manifest."""
        manifest = Manifest.create_new(
            s3_endpoint='https://example.com',
            s3_bucket='bucket',
            s3_prefix='prefix',
        )
        
        assert manifest.s3_endpoint == 'https://example.com'
        assert manifest.created_at is not None
    
    def test_add_record(self, sample_manifest):
        """Test adding a record updates stats."""
        initial_count = sample_manifest.total_images
        
        new_record = ImageRecord(
            original_key='attachments/botany/originals/new.jpg',
            original_size=500000,
            original_modified='2026-01-10',
            base_thumbnail_key='attachments/botany/thumbnails/new.jpg',
            collection='botany',
            filename='new.jpg',
        )
        
        sample_manifest.add_record(new_record)
        
        assert sample_manifest.total_images == initial_count + 1
    
    def test_total_images(self, sample_manifest):
        """Test total image count."""
        assert sample_manifest.total_images == 3
    
    def test_total_with_thumbnails(self, sample_manifest):
        """Test count of images with thumbnails."""
        assert sample_manifest.total_with_thumbnails == 1
    
    def test_total_missing_thumbnails(self, sample_manifest):
        """Test count of images missing thumbnails."""
        assert sample_manifest.total_missing_thumbnails == 2
    
    def test_get_records_needing_thumbnails(self, sample_manifest):
        """Test filtering records needing thumbnails."""
        records = list(sample_manifest.get_records_needing_thumbnails())
        
        assert len(records) == 2
        assert all(r.needs_thumbnail() for r in records)
    
    def test_get_records_for_collection(self, sample_manifest):
        """Test filtering records by collection."""
        records = list(sample_manifest.get_records_for_collection('botany'))
        
        assert len(records) == 2
        assert all(r.collection == 'botany' for r in records)
    
    def test_is_stale_fresh(self, sample_manifest):
        """Test is_stale returns False for fresh manifest."""
        assert sample_manifest.is_stale() is False
    
    def test_is_stale_old(self, stale_manifest):
        """Test is_stale returns True for old manifest."""
        assert stale_manifest.is_stale() is True
    
    def test_to_dict_and_from_dict(self, sample_manifest):
        """Test serialization round-trip."""
        data = sample_manifest.to_dict()
        loaded = Manifest.from_dict(data)
        
        assert loaded.s3_endpoint == sample_manifest.s3_endpoint
        assert loaded.total_images == sample_manifest.total_images
    
    def test_save_and_load(self, sample_manifest):
        """Test saving and loading manifest."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            filepath = f.name
        
        try:
            sample_manifest.save(filepath)
            loaded = Manifest.load(filepath)
            
            assert loaded.total_images == sample_manifest.total_images
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)
    
    def test_load_file_not_found(self):
        """Test loading non-existent file raises error."""
        with pytest.raises(FileNotFoundError):
            Manifest.load('/nonexistent/path/manifest.json')
