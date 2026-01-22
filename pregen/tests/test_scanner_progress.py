"""Tests for ScannerProgress class."""

import pytest
from pregen.scanner_progress import ScannerProgress
from pregen.image_record import ImageRecord


class TestScannerProgress:
    """Tests for ScannerProgress class."""
    
    def test_init_defaults(self, logger):
        """Test default initialization."""
        progress = ScannerProgress(logger=logger)
        
        assert progress.show_files is False
        assert progress.log_interval == 500
    
    def test_init_show_files(self, logger):
        """Test show_files initialization."""
        progress = ScannerProgress(show_files=True, logger=logger)
        
        assert progress.show_files is True
    
    def test_on_file_scanned_updates_counts(self, logger, sample_image_record):
        """Test that file scanning updates counts."""
        progress = ScannerProgress(logger=logger)
        
        progress.on_file_scanned(sample_image_record)
        
        assert progress.collection_counts['botany'] == 1
    
    def test_callable_interface(self, logger, sample_image_record):
        """Test using progress as callback."""
        progress = ScannerProgress(logger=logger)
        
        progress(sample_image_record)
        
        assert progress.collection_counts['botany'] == 1
    
    def test_show_files_output(self, logger, sample_image_record, capsys):
        """Test show_files mode prints each file."""
        progress = ScannerProgress(show_files=True, logger=logger)
        
        progress.on_file_scanned(sample_image_record)
        
        captured = capsys.readouterr()
        assert 'image1.jpg' in captured.out
        assert '@200' in captured.out  # New format shows scale
