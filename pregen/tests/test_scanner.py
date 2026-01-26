"""Tests for Scanner class."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from pregen.scanner import Scanner
from pregen.s3_client import S3Client
from pregen.s3_config import S3Config


class TestScanner:
    """Tests for Scanner class."""
    
    @pytest.fixture
    def config(self):
        """Fixture providing S3 config."""
        return S3Config(
            endpoint='https://test-endpoint.example.com:9000',
            bucket='test-bucket',
            prefix='attachments',
            access_key='test-access-key',
            secret_key='test-secret-key',
            region='us-east-1',
        )
    
    @pytest.fixture
    def s3_client_with_mock(self, config):
        """Fixture providing S3Client with mocked boto3."""
        mock_boto = MagicMock()
        with patch('pregen.s3_client.boto3.client', return_value=mock_boto):
            client = S3Client(config)
            client._test_mock = mock_boto
            yield client
    
    def test_init(self, s3_client_with_mock, logger):
        """Test Scanner initialization."""
        scanner = Scanner(s3_client_with_mock, logger)
        
        assert scanner.s3 == s3_client_with_mock
    
    def test_scan_discovers_collections(self, s3_client_with_mock, logger):
        """Test that scan discovers collections when none specified."""
        # Setup mock for list_collections
        s3_client_with_mock._test_mock.list_objects_v2.return_value = {
            'CommonPrefixes': [
                {'Prefix': 'attachments/botany/'},
            ]
        }
        
        # Setup mock for list_originals/list_thumbnails (empty)
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{'Contents': []}]
        s3_client_with_mock._test_mock.get_paginator.return_value = mock_paginator
        
        scanner = Scanner(s3_client_with_mock, logger)
        manifest = scanner.scan()
        
        assert 'botany' in manifest.collections
    
    def test_scan_with_specified_collections(self, s3_client_with_mock, logger):
        """Test scanning only specified collections."""
        # Setup mock for list_originals/list_thumbnails (empty)
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{'Contents': []}]
        s3_client_with_mock._test_mock.get_paginator.return_value = mock_paginator
        
        scanner = Scanner(s3_client_with_mock, logger)
        manifest = scanner.scan(collections=['botany'])
        
        assert manifest.collections == ['botany']
    
    def test_scan_sets_duration(self, s3_client_with_mock, logger):
        """Test that scan duration is recorded."""
        # Setup mock for list_originals/list_thumbnails (empty)
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{'Contents': []}]
        s3_client_with_mock._test_mock.get_paginator.return_value = mock_paginator
        
        scanner = Scanner(s3_client_with_mock, logger)
        manifest = scanner.scan(collections=['botany'])
        
        assert manifest.scan_duration_seconds >= 0
