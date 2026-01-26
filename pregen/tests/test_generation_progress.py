"""Tests for GenerationProgress class."""

import pytest
from pregen.generation_progress import GenerationProgress
from pregen.generation_stats import GenerationStats
from pregen.image_record import ImageRecord


class TestGenerationProgress:
    """Tests for GenerationProgress class."""
    
    def test_init_defaults(self, logger):
        """Test default initialization."""
        progress = GenerationProgress(logger=logger)
        
        assert progress.show_files is False
        assert progress.log_interval == 100
    
    def test_init_show_files(self, logger):
        """Test show_files initialization."""
        progress = GenerationProgress(show_files=True, logger=logger)
        
        assert progress.show_files is True
    
    def test_on_file_processed_success_show_files(self, logger, sample_image_record, capsys):
        """Test show_files output for successful processing."""
        progress = GenerationProgress(show_files=True, logger=logger)
        
        progress.on_file_processed(sample_image_record, success=True, thumb_size=5000)
        
        captured = capsys.readouterr()
        assert 'OK' in captured.out
        assert 'image1.jpg' in captured.out
    
    def test_on_file_processed_error_show_files(self, logger, sample_image_record, capsys):
        """Test show_files output for failed processing."""
        progress = GenerationProgress(show_files=True, logger=logger)
        
        progress.on_file_processed(sample_image_record, success=False, error='test error')
        
        captured = capsys.readouterr()
        assert 'ERROR' in captured.out
        assert 'test error' in captured.out
    
    def test_on_dry_run_show_files(self, logger, sample_image_record, capsys):
        """Test show_files output for dry run."""
        progress = GenerationProgress(show_files=True, logger=logger)
        
        progress.on_dry_run(sample_image_record)
        
        captured = capsys.readouterr()
        assert 'DRY RUN' in captured.out
    
    def test_callable_interface(self, logger):
        """Test using progress as callback."""
        progress = GenerationProgress(logger=logger)
        stats = GenerationStats(total_to_process=100)
        stats.processed = 100
        
        progress(stats)
        
        assert progress.last_logged == 100
