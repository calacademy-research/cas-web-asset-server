"""
Pytest fixtures for pregen tests.
"""

import pytest
from datetime import datetime, timedelta


@pytest.fixture
def s3_config():
    """Fixture providing S3 configuration."""
    from pregen.s3_config import S3Config
    
    return S3Config(
        endpoint='https://test-endpoint.example.com:9000',
        bucket='test-bucket',
        prefix='attachments',
        access_key='test-access-key',
        secret_key='test-secret-key',
        region='us-east-1',
    )


@pytest.fixture
def mock_boto3_client(mocker):
    """Fixture providing a mocked boto3 client."""
    mock_client = mocker.MagicMock()
    mocker.patch('boto3.client', return_value=mock_client)
    return mock_client


@pytest.fixture
def mock_s3_client(s3_config):
    """Fixture providing an S3Client with mocked boto3."""
    from unittest.mock import MagicMock, patch
    from pregen.s3_client import S3Client
    
    # Create a mock boto3 client
    mock_boto = MagicMock()
    
    # Patch boto3.client to return our mock
    with patch('boto3.client', return_value=mock_boto):
        client = S3Client(s3_config)
        # Store reference to the mock for test setup
        client._mock_boto = mock_boto
        yield client


@pytest.fixture
def simple_mock_storage_client():
    """Fixture providing a simple mock storage client for generator tests."""
    from unittest.mock import MagicMock
    mock = MagicMock()
    mock.download_object.return_value = b'fake image data'
    mock.upload_object.return_value = None
    mock.config = MagicMock()
    mock.config.prefix = 'attachments'
    return mock


@pytest.fixture
def sample_image_bytes():
    """Fixture providing sample JPEG image bytes."""
    from PIL import Image
    import io
    
    # Create a simple test image
    img = Image.new('RGB', (100, 100), color='red')
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG')
    return buffer.getvalue()


@pytest.fixture
def sample_png_bytes():
    """Fixture providing sample PNG image bytes."""
    from PIL import Image
    import io
    
    # Create a simple test image with transparency
    img = Image.new('RGBA', (100, 100), color=(255, 0, 0, 128))
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    return buffer.getvalue()


@pytest.fixture
def sample_image_record():
    """Fixture providing a sample image record with a thumbnail."""
    from pregen.image_record import ImageRecord, ThumbnailInfo
    
    record = ImageRecord(
        original_key='attachments/botany/originals/a8/96/image1.jpg',
        original_size=1000000,
        original_modified='2026-01-01T00:00:00',
        base_thumbnail_key='attachments/botany/thumbnails/a8/96/image1.jpg',
        collection='botany',
        filename='image1.jpg',
    )
    # Add a thumbnail at scale 200
    record.add_thumbnail(ThumbnailInfo(
        scale=200,
        key='attachments/botany/thumbnails/a8/96/image1_200.jpg',
        size=50000,
        modified='2026-01-01T00:00:00',
    ))
    return record


@pytest.fixture
def sample_image_record_no_thumbnail():
    """Fixture providing a sample image record without thumbnails."""
    from pregen.image_record import ImageRecord
    
    return ImageRecord(
        original_key='attachments/botany/originals/b2/c3/image2.jpg',
        original_size=2000000,
        original_modified='2026-01-02T00:00:00',
        base_thumbnail_key='attachments/botany/thumbnails/b2/c3/image2.jpg',
        collection='botany',
        filename='image2.jpg',
    )


@pytest.fixture
def sample_manifest():
    """Fixture providing a sample manifest with records."""
    from pregen.manifest import Manifest
    from pregen.image_record import ImageRecord, ThumbnailInfo
    
    manifest = Manifest(
        created_at=datetime.now().isoformat(),
        s3_endpoint='https://test-endpoint.example.com:9000',
        s3_bucket='test-bucket',
        s3_prefix='attachments',
        collections=['botany', 'ichthyology'],
        scan_duration_seconds=10.5,
    )
    
    # Record 1: has thumbnail at 200px
    record1 = ImageRecord(
        original_key='attachments/botany/originals/a8/96/image1.jpg',
        original_size=1000000,
        original_modified='2026-01-01T00:00:00',
        base_thumbnail_key='attachments/botany/thumbnails/a8/96/image1.jpg',
        collection='botany',
        filename='image1.jpg',
    )
    record1.add_thumbnail(ThumbnailInfo(
        scale=200,
        key='attachments/botany/thumbnails/a8/96/image1_200.jpg',
        size=50000,
        modified='2026-01-01T00:00:00',
    ))
    
    # Record 2: no thumbnail (botany)
    record2 = ImageRecord(
        original_key='attachments/botany/originals/b2/c3/image2.jpg',
        original_size=2000000,
        original_modified='2026-01-02T00:00:00',
        base_thumbnail_key='attachments/botany/thumbnails/b2/c3/image2.jpg',
        collection='botany',
        filename='image2.jpg',
    )
    
    # Record 3: no thumbnail (ichthyology)
    record3 = ImageRecord(
        original_key='attachments/ichthyology/originals/d4/e5/image3.jpg',
        original_size=1500000,
        original_modified='2026-01-03T00:00:00',
        base_thumbnail_key='attachments/ichthyology/thumbnails/d4/e5/image3.jpg',
        collection='ichthyology',
        filename='image3.jpg',
    )
    
    for record in [record1, record2, record3]:
        manifest.add_record(record)
    
    return manifest


@pytest.fixture
def stale_manifest(sample_manifest):
    """Fixture providing a stale manifest (>24 hours old)."""
    old_time = datetime.now() - timedelta(hours=48)
    sample_manifest.created_at = old_time.isoformat()
    return sample_manifest


@pytest.fixture
def empty_manifest():
    """Fixture providing an empty manifest."""
    from pregen.manifest import Manifest
    
    return Manifest(
        created_at=datetime.now().isoformat(),
        s3_endpoint='https://test-endpoint.example.com:9000',
        s3_bucket='test-bucket',
        s3_prefix='attachments',
        collections=[],
        scan_duration_seconds=0,
    )


@pytest.fixture
def temp_manifest_file(sample_manifest, tmp_path):
    """Fixture providing a temporary manifest file."""
    filepath = tmp_path / "test_manifest.json"
    sample_manifest.save(str(filepath))
    return str(filepath)


@pytest.fixture
def logger():
    """Fixture providing a logger."""
    import logging
    return logging.getLogger('test')
