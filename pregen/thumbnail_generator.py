"""
ThumbnailGenerator - Handles image resizing and thumbnail generation.
"""

import io
import logging
import os
from typing import Optional, Tuple

from PIL import Image


class ThumbnailGenerator:
    """
    Generates thumbnails from original images using Pillow.
    """
    
    CONTENT_TYPES = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.tif': 'image/jpeg',
        '.tiff': 'image/jpeg',
        '.bmp': 'image/jpeg',
    }
    
    def __init__(
        self, 
        size: int = 200, 
        quality: int = 85,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize thumbnail generator.
        
        Args:
            size: Maximum dimension for thumbnails (default: 200)
            quality: JPEG quality for output (default: 85)
            logger: Optional logger instance
        """
        self.size = size
        self.quality = quality
        self.logger = logger or logging.getLogger(__name__)
    
    def generate(
        self, 
        image_data: bytes, 
        original_extension: str
    ) -> Tuple[bytes, str]:
        """
        Generate a thumbnail from image data.
        
        Args:
            image_data: Original image as bytes
            original_extension: Original file extension (e.g., '.jpg')
            
        Returns:
            Tuple of (thumbnail_bytes, content_type)
        """
        try:
            img = Image.open(io.BytesIO(image_data))
            img = self._convert_color_mode(img)
            img.thumbnail((self.size, self.size), Image.Resampling.LANCZOS)
            
            output = io.BytesIO()
            output_format, content_type = self._get_output_format(original_extension)
            
            if output_format == 'JPEG':
                img.save(output, format='JPEG', quality=self.quality, optimize=True)
            elif output_format == 'PNG':
                img.save(output, format='PNG', optimize=True)
            elif output_format == 'GIF':
                img.save(output, format='GIF')
            else:
                img.save(output, format='JPEG', quality=self.quality, optimize=True)
                content_type = 'image/jpeg'
            
            return output.getvalue(), content_type
            
        except Exception as e:
            self.logger.error(f"Error generating thumbnail: {e}")
            raise
    
    def _convert_color_mode(self, img: Image.Image) -> Image.Image:
        """Convert image to appropriate color mode for output."""
        if img.mode in ('RGBA', 'LA'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'LA':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1])
            return background
        elif img.mode == 'P':
            img = img.convert('RGBA')
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1])
            return background
        elif img.mode != 'RGB':
            return img.convert('RGB')
        return img
    
    def _get_output_format(self, extension: str) -> Tuple[str, str]:
        """Determine output format based on original extension."""
        ext_lower = extension.lower()
        
        if ext_lower in ('.jpg', '.jpeg', '.tif', '.tiff', '.bmp'):
            return 'JPEG', 'image/jpeg'
        elif ext_lower == '.png':
            return 'PNG', 'image/png'
        elif ext_lower == '.gif':
            return 'GIF', 'image/gif'
        else:
            return 'JPEG', 'image/jpeg'
    
    def get_content_type(self, extension: str) -> str:
        """Get content type for a file extension."""
        return self.CONTENT_TYPES.get(extension.lower(), 'image/jpeg')
