"""Tests for Reporter class."""

import io
import pytest
from pregen.reporter import Reporter


class TestReporter:
    """Tests for Reporter class."""
    
    def test_init_default_output(self):
        """Test default output is stdout."""
        import sys
        reporter = Reporter()
        assert reporter.output == sys.stdout
    
    def test_init_custom_output(self):
        """Test custom output stream."""
        output = io.StringIO()
        reporter = Reporter(output=output)
        assert reporter.output == output
    
    def test_format_bytes(self):
        """Test byte formatting."""
        reporter = Reporter()
        
        assert reporter._format_bytes(500) == '500.0 B'
        assert reporter._format_bytes(1024) == '1.0 KB'
        assert reporter._format_bytes(1024 * 1024) == '1.0 MB'
    
    def test_format_duration(self):
        """Test duration formatting."""
        reporter = Reporter()
        
        assert reporter._format_duration(30) == '30.0 seconds'
        assert reporter._format_duration(90) == '1.5 minutes'
        assert reporter._format_duration(3600) == '1.0 hours'
    
    def test_report_summary(self, sample_manifest):
        """Test summary report generation."""
        output = io.StringIO()
        reporter = Reporter(output=output)
        
        reporter.report_summary(sample_manifest)
        
        result = output.getvalue()
        assert 'SUMMARY' in result
        assert 'Total Images:' in result
        assert 'botany' in result
    
    def test_report_summary_stale_warning(self, stale_manifest):
        """Test stale manifest warning."""
        output = io.StringIO()
        reporter = Reporter(output=output)
        
        reporter.report_summary(stale_manifest)
        
        result = output.getvalue()
        assert 'WARNING' in result
    
    def test_report_detailed(self, sample_manifest):
        """Test detailed report includes storage stats."""
        output = io.StringIO()
        reporter = Reporter(output=output)
        
        reporter.report_detailed(sample_manifest)
        
        result = output.getvalue()
        assert 'Storage Statistics' in result
    
    def test_report_action_plan(self, sample_manifest):
        """Test action plan report."""
        output = io.StringIO()
        reporter = Reporter(output=output)
        
        reporter.report_action_plan(sample_manifest, size=200, cadence=1.0)
        
        result = output.getvalue()
        assert 'ACTION PLAN' in result
        assert '200px' in result
    
    def test_report_missing_files(self, sample_manifest):
        """Test missing files report."""
        output = io.StringIO()
        reporter = Reporter(output=output)
        
        reporter.report_missing_files(sample_manifest)
        
        result = output.getvalue()
        assert 'MISSING THUMBNAILS' in result
        assert 'image2.jpg' in result
