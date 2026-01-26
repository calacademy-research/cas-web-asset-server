"""Tests for Generator class."""

from unittest.mock import MagicMock
import pytest

from pregen.generator import Generator
from pregen.thumbnail_generator import ThumbnailGenerator


class TestGenerator:
    """Tests for Generator class."""
    
    @pytest.fixture
    def mock_storage(self):
        """Create a mock storage client."""
        mock = MagicMock()
        mock.download_object.return_value = b'fake image data'
        mock.upload_object.return_value = None
        mock.config.prefix = 'attachments'
        return mock
    
    @pytest.fixture
    def mock_thumb_gen(self):
        """Create a mock thumbnail generator."""
        gen = MagicMock(spec=ThumbnailGenerator)
        gen.generate.return_value = (b'thumbnail data', 'image/jpeg')
        gen.size = 200  # Required attribute
        return gen
    
    def test_init(self, mock_storage, mock_thumb_gen, logger):
        """Test Generator initialization."""
        generator = Generator(
            s3_client=mock_storage,
            thumbnail_generator=mock_thumb_gen,
            cadence=0.5,
            dry_run=True,
            logger=logger,
        )
        
        assert generator.cadence == 0.5
        assert generator.dry_run is True
    
    def test_generate_dry_run(self, mock_storage, mock_thumb_gen, sample_manifest, logger):
        """Test generation in dry run mode."""
        generator = Generator(
            s3_client=mock_storage,
            thumbnail_generator=mock_thumb_gen,
            cadence=0,
            dry_run=True,
            logger=logger,
        )
        
        stats = generator.generate_from_manifest(sample_manifest)
        
        assert stats.processed == 2
        mock_storage.download_object.assert_not_called()
    
    def test_generate_actual(self, mock_storage, mock_thumb_gen, sample_manifest, logger):
        """Test actual generation."""
        mock_storage.download_object.return_value = b'image data'
        
        generator = Generator(
            s3_client=mock_storage,
            thumbnail_generator=mock_thumb_gen,
            cadence=0,
            dry_run=False,
            logger=logger,
        )
        
        stats = generator.generate_from_manifest(sample_manifest)
        
        assert stats.processed == 2
        assert mock_storage.download_object.call_count == 2
    
    def test_generate_with_collection_filter(self, mock_storage, mock_thumb_gen, sample_manifest, logger):
        """Test filtering by collection."""
        generator = Generator(
            s3_client=mock_storage,
            thumbnail_generator=mock_thumb_gen,
            cadence=0,
            dry_run=True,
            logger=logger,
        )
        
        stats = generator.generate_from_manifest(sample_manifest, collections=['botany'])
        
        assert stats.processed == 1
    
    def test_generate_handles_errors(self, mock_storage, mock_thumb_gen, sample_manifest, logger):
        """Test error handling during generation."""
        mock_storage.download_object.side_effect = Exception("Download failed")
        
        generator = Generator(
            s3_client=mock_storage,
            thumbnail_generator=mock_thumb_gen,
            cadence=0,
            dry_run=False,
            logger=logger,
        )
        
        stats = generator.generate_from_manifest(sample_manifest)
        
        assert stats.errors == 2
        assert stats.processed == 0
    
    def test_generate_can_be_stopped(self, mock_storage, mock_thumb_gen, sample_manifest, logger):
        """Test stopping generation."""
        generator = Generator(
            s3_client=mock_storage,
            thumbnail_generator=mock_thumb_gen,
            cadence=0,
            dry_run=True,
            logger=logger,
        )
        
        generator.stop()
        stats = generator.generate_from_manifest(sample_manifest)
        
        assert stats.processed == 0
