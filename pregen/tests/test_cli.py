"""Tests for CLI module."""

import os
import pytest
from pregen.cli import create_parser, main, cmd_report


class TestCreateParser:
    """Tests for argument parser creation."""
    
    def test_parser_created(self):
        """Test parser is created successfully."""
        parser = create_parser()
        assert parser is not None
    
    def test_scan_command(self):
        """Test scan command parsing."""
        parser = create_parser()
        args = parser.parse_args(['scan', '-o', 'test.json'])
        
        assert args.command == 'scan'
        assert args.output == 'test.json'
    
    def test_scan_show_files(self):
        """Test scan show_files flag."""
        parser = create_parser()
        args = parser.parse_args(['scan', '--show-files'])
        
        assert args.show_files is True
    
    def test_generate_command(self):
        """Test generate command parsing."""
        parser = create_parser()
        args = parser.parse_args([
            'generate', '-m', 'manifest.json',
            '--size', '150', '--cadence', '0.5'
        ])
        
        assert args.command == 'generate'
        assert args.size == 150
        assert args.cadence == 0.5
    
    def test_generate_show_files(self):
        """Test generate show_files flag."""
        parser = create_parser()
        args = parser.parse_args(['generate', '-m', 'manifest.json', '--show-files'])
        
        assert args.show_files is True
    
    def test_report_command(self):
        """Test report command parsing."""
        parser = create_parser()
        args = parser.parse_args(['report', '-m', 'manifest.json', '--type', 'plan'])
        
        assert args.command == 'report'
        assert args.type == 'plan'


class TestMain:
    """Tests for main entry point."""
    
    def test_no_command(self):
        """Test running without command shows help."""
        result = main([])
        assert result == 1


class TestCmdReport:
    """Tests for report command."""
    
    def test_report_file_not_found(self):
        """Test report with non-existent manifest."""
        parser = create_parser()
        args = parser.parse_args(['report', '-m', '/nonexistent/manifest.json'])
        args.verbose = False
        
        result = cmd_report(args)
        
        assert result == 1
    
    def test_report_success(self, temp_manifest_file, capsys):
        """Test successful report generation."""
        parser = create_parser()
        args = parser.parse_args(['report', '-m', temp_manifest_file, '--type', 'summary'])
        args.verbose = False
        
        result = cmd_report(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert 'SUMMARY' in captured.out
