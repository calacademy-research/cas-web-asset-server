"""Tests for S3Client class."""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError

from pregen.s3_client import S3Client
from pregen.s3_config import S3Config


class TestS3Client:
    """Tests for S3Client class."""
    
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
    def client_with_mock(self, config):
        """Fixture providing S3Client with mocked boto3."""
        mock_boto = MagicMock()
        with patch('pregen.s3_client.boto3.client', return_value=mock_boto):
            client = S3Client(config)
            # Store ref so tests can configure mock behavior
            client._test_mock = mock_boto
            yield client
    
    def test_list_collections(self, client_with_mock):
        """Test listing collections."""
        client_with_mock._test_mock.list_objects_v2.return_value = {
            'CommonPrefixes': [
                {'Prefix': 'attachments/botany/'},
                {'Prefix': 'attachments/ichthyology/'},
            ]
        }
        
        collections = client_with_mock.list_collections()
        
        assert collections == ['botany', 'ichthyology']
    
    def test_list_collections_empty(self, client_with_mock):
        """Test listing collections when none exist."""
        client_with_mock._test_mock.list_objects_v2.return_value = {}
        
        collections = client_with_mock.list_collections()
        
        assert collections == []
    
    def test_list_originals(self, client_with_mock):
        """Test listing original images."""
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                'Contents': [
                    {
                        'Key': 'attachments/botany/originals/a8/96/image1.jpg',
                        'Size': 1000000,
                        'LastModified': datetime(2026, 1, 1),
                    },
                    {
                        'Key': 'attachments/botany/originals/c3/d4/readme.txt',
                        'Size': 100,
                        'LastModified': datetime(2026, 1, 3),
                    },
                ]
            }
        ]
        client_with_mock._test_mock.get_paginator.return_value = mock_paginator
        
        results = list(client_with_mock.list_originals('botany'))
        
        assert len(results) == 1  # Only .jpg, not .txt
        assert results[0]['key'].endswith('.jpg')
    
    def test_get_thumbnail_key(self):
        """Test converting original key to thumbnail key."""
        original = 'attachments/botany/originals/a8/96/image.jpg'
        expected = 'attachments/botany/thumbnails/a8/96/image.jpg'
        
        result = S3Client.get_thumbnail_key(original)
        
        assert result == expected
    
    def test_get_original_key(self):
        """Test converting thumbnail key to original key."""
        thumbnail = 'attachments/botany/thumbnails/a8/96/image.jpg'
        expected = 'attachments/botany/originals/a8/96/image.jpg'
        
        result = S3Client.get_original_key(thumbnail)
        
        assert result == expected
    
    def test_object_exists_true(self, client_with_mock):
        """Test object_exists returns True when object exists."""
        client_with_mock._test_mock.head_object.return_value = {}
        
        result = client_with_mock.object_exists('some/key.jpg')
        
        assert result is True
    
    def test_object_exists_false(self, client_with_mock):
        """Test object_exists returns False when object doesn't exist."""
        client_with_mock._test_mock.head_object.side_effect = ClientError(
            {'Error': {'Code': '404'}},
            'HeadObject'
        )
        
        result = client_with_mock.object_exists('nonexistent/key.jpg')
        
        assert result is False
    
    def test_download_object(self, client_with_mock):
        """Test downloading an object."""
        mock_body = MagicMock()
        mock_body.read.return_value = b'image data'
        client_with_mock._test_mock.get_object.return_value = {'Body': mock_body}
        
        result = client_with_mock.download_object('some/key.jpg')
        
        assert result == b'image data'
    
    def test_upload_object(self, client_with_mock):
        """Test uploading an object."""
        client_with_mock.upload_object('some/key.jpg', b'data', 'image/jpeg')
        
        client_with_mock._test_mock.put_object.assert_called_once()
    
    def test_image_extensions(self):
        """Test that IMAGE_EXTENSIONS contains expected formats."""
        expected = {'.jpg', '.jpeg', '.png', '.gif', '.tif', '.tiff', '.bmp'}
        assert S3Client.IMAGE_EXTENSIONS == expected
