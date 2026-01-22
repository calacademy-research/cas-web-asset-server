"""
Tests for ImageRecord.
"""

import pytest
from pregen.image_record import ImageRecord, ThumbnailInfo


class TestThumbnailInfo:
    """Tests for ThumbnailInfo dataclass."""
    
    def test_create_info(self):
        """Test creating thumbnail info."""
        info = ThumbnailInfo(
            scale=200,
            key='attachments/botany/thumbnails/a8/96/image_200.jpg',
            size=50000,
            modified='2026-01-01T00:00:00',
        )
        assert info.scale == 200
        assert info.size == 50000
    
    def test_to_dict(self):
        """Test converting to dict."""
        info = ThumbnailInfo(
            scale=200,
            key='key_200.jpg',
            size=50000,
            modified='2026-01-01T00:00:00',
        )
        d = info.to_dict()
        assert d['scale'] == 200
        assert d['size'] == 50000
    
    def test_from_dict(self):
        """Test creating from dict."""
        d = {
            'scale': 400,
            'key': 'key_400.jpg',
            'size': 100000,
            'modified': '2026-01-02T00:00:00',
        }
        info = ThumbnailInfo.from_dict(d)
        assert info.scale == 400
        assert info.size == 100000


class TestImageRecord:
    """Tests for ImageRecord dataclass."""
    
    def test_create_record(self):
        """Test creating an image record."""
        record = ImageRecord(
            original_key='attachments/botany/originals/a8/96/image.jpg',
            original_size=1000000,
            original_modified='2026-01-01T00:00:00',
            base_thumbnail_key='attachments/botany/thumbnails/a8/96/image.jpg',
            collection='botany',
            filename='image.jpg',
        )
        
        assert record.collection == 'botany'
        assert record.filename == 'image.jpg'
        assert record.original_size == 1000000
        assert record.thumbnail_exists == False  # No thumbnails added yet
    
    def test_add_thumbnail(self):
        """Test adding a thumbnail."""
        record = ImageRecord(
            original_key='key',
            original_size=1000,
            original_modified='2026-01-01',
            base_thumbnail_key='thumb_key.jpg',
            collection='test',
            filename='file.jpg',
        )
        
        record.add_thumbnail(ThumbnailInfo(
            scale=200,
            key='thumb_key_200.jpg',
            size=5000,
            modified='2026-01-01',
        ))
        
        assert record.has_thumbnail(200)
        assert not record.has_thumbnail(400)
        assert record.thumbnail_exists  # Legacy property
    
    def test_needs_thumbnail_true(self):
        """Test needs_thumbnail returns True when missing."""
        record = ImageRecord(
            original_key='key',
            original_size=1000,
            original_modified='2026-01-01',
            base_thumbnail_key='thumb_key.jpg',
            collection='test',
            filename='file.jpg',
        )
        
        assert record.needs_thumbnail()  # No thumbnails at all
        assert record.needs_thumbnail(200)  # Specific scale missing
    
    def test_needs_thumbnail_false(self):
        """Test needs_thumbnail returns False when exists."""
        record = ImageRecord(
            original_key='key',
            original_size=1000,
            original_modified='2026-01-01',
            base_thumbnail_key='thumb_key.jpg',
            collection='test',
            filename='file.jpg',
        )
        record.add_thumbnail(ThumbnailInfo(
            scale=200,
            key='thumb_key_200.jpg',
            size=5000,
            modified='2026-01-01',
        ))
        
        assert not record.needs_thumbnail()  # Has at least one thumbnail
        assert not record.needs_thumbnail(200)  # Specific scale exists
        assert record.needs_thumbnail(400)  # Different scale missing
    
    def test_get_thumbnail_key(self):
        """Test generating thumbnail key with scale suffix."""
        record = ImageRecord(
            original_key='key',
            original_size=1000,
            original_modified='2026-01-01',
            base_thumbnail_key='attachments/botany/thumbnails/a8/96/image.jpg',
            collection='test',
            filename='image.jpg',
        )
        
        assert record.get_thumbnail_key(200) == 'attachments/botany/thumbnails/a8/96/image_200.jpg'
        assert record.get_thumbnail_key(400) == 'attachments/botany/thumbnails/a8/96/image_400.jpg'
    
    def test_to_dict(self, sample_image_record):
        """Test converting to dict."""
        d = sample_image_record.to_dict()
        
        assert 'original_key' in d
        assert 'base_thumbnail_key' in d
        assert 'thumbnails' in d
        assert '200' in d['thumbnails']  # Scale keys are strings in JSON
    
    def test_from_dict(self):
        """Test creating from dict."""
        d = {
            'original_key': 'originals/image.jpg',
            'original_size': 1000,
            'original_modified': '2026-01-01',
            'base_thumbnail_key': 'thumbnails/image.jpg',
            'collection': 'test',
            'filename': 'image.jpg',
            'thumbnails': {
                '200': {
                    'scale': 200,
                    'key': 'thumbnails/image_200.jpg',
                    'size': 5000,
                    'modified': '2026-01-01',
                }
            }
        }
        
        record = ImageRecord.from_dict(d)
        assert record.collection == 'test'
        assert record.has_thumbnail(200)
        assert record.thumbnails[200].size == 5000
    
    def test_from_dict_legacy_format(self):
        """Test creating from legacy dict format."""
        d = {
            'original_key': 'originals/image.jpg',
            'original_size': 1000,
            'original_modified': '2026-01-01',
            'thumbnail_key': 'thumbnails/image.jpg',  # Legacy field name
            'thumbnail_exists': True,
            'thumbnail_size': 5000,
            'thumbnail_modified': '2026-01-01',
            'collection': 'test',
            'filename': 'image.jpg',
        }
        
        record = ImageRecord.from_dict(d)
        assert record.collection == 'test'
        assert record.thumbnail_exists
    
    def test_format_status_exists(self, sample_image_record):
        """Test format_status when thumbnail exists."""
        status = sample_image_record.format_status()
        
        assert sample_image_record.filename in status
        assert '@200' in status
    
    def test_format_status_missing(self):
        """Test format_status when thumbnail missing."""
        record = ImageRecord(
            original_key='key',
            original_size=1000,
            original_modified='2026-01-01',
            base_thumbnail_key='thumb_key.jpg',
            collection='test',
            filename='missing.jpg',
        )
        
        status = record.format_status()
        assert 'missing.jpg' in status
        assert 'NO thumbnails' in status
    
    def test_available_scales(self):
        """Test getting available scales."""
        record = ImageRecord(
            original_key='key',
            original_size=1000,
            original_modified='2026-01-01',
            base_thumbnail_key='thumb_key.jpg',
            collection='test',
            filename='file.jpg',
        )
        
        record.add_thumbnail(ThumbnailInfo(scale=200, key='k_200.jpg', size=1000, modified='2026-01-01'))
        record.add_thumbnail(ThumbnailInfo(scale=400, key='k_400.jpg', size=2000, modified='2026-01-01'))
        
        assert record.available_scales == [200, 400]
