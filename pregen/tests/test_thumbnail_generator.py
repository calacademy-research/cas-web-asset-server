"""Tests for ThumbnailGenerator class."""

import io
import pytest

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from pregen.thumbnail_generator import ThumbnailGenerator


@pytest.mark.skipif(not HAS_PIL, reason="Pillow not installed")
class TestThumbnailGenerator:
    """Tests for ThumbnailGenerator class."""
    
    def test_init_defaults(self):
        """Test default initialization."""
        gen = ThumbnailGenerator()
        
        assert gen.size == 200
        assert gen.quality == 85
    
    def test_init_custom_values(self):
        """Test initialization with custom values."""
        gen = ThumbnailGenerator(size=300, quality=90)
        
        assert gen.size == 300
        assert gen.quality == 90
    
    def test_generate_jpeg(self, sample_image_bytes):
        """Test generating thumbnail from JPEG."""
        gen = ThumbnailGenerator(size=50)
        
        thumb_data, content_type = gen.generate(sample_image_bytes, '.jpg')
        
        assert content_type == 'image/jpeg'
        assert len(thumb_data) > 0
        
        img = Image.open(io.BytesIO(thumb_data))
        assert img.size[0] <= 50
        assert img.size[1] <= 50
    
    def test_generate_png(self, sample_png_bytes):
        """Test generating thumbnail from PNG."""
        gen = ThumbnailGenerator(size=50)
        
        thumb_data, content_type = gen.generate(sample_png_bytes, '.png')
        
        assert content_type == 'image/png'
        assert len(thumb_data) > 0
    
    def test_generate_maintains_aspect_ratio(self):
        """Test that aspect ratio is maintained."""
        img = Image.new('RGB', (200, 100), color='blue')
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG')
        
        gen = ThumbnailGenerator(size=50)
        thumb_data, _ = gen.generate(buffer.getvalue(), '.jpg')
        
        result = Image.open(io.BytesIO(thumb_data))
        assert result.size[0] == 50
        assert result.size[1] == 25
    
    def test_generate_invalid_image(self):
        """Test handling of invalid image data."""
        gen = ThumbnailGenerator(size=50)
        
        with pytest.raises(Exception):
            gen.generate(b'not an image', '.jpg')
    
    def test_get_content_type(self):
        """Test getting content type for extensions."""
        gen = ThumbnailGenerator()
        
        assert gen.get_content_type('.jpg') == 'image/jpeg'
        assert gen.get_content_type('.JPG') == 'image/jpeg'
        assert gen.get_content_type('.png') == 'image/png'
        assert gen.get_content_type('.unknown') == 'image/jpeg'
