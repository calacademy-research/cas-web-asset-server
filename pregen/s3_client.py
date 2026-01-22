"""
S3Client - S3/MinIO operations for listing, downloading, and uploading files.
"""

import logging
import os
from typing import Generator, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .s3_config import S3Config


class S3Client:
    """
    Wrapper for S3/MinIO operations.
    
    Provides methods for listing objects, checking existence,
    downloading and uploading files.
    """
    
    IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.tif', '.tiff', '.bmp'}
    
    def __init__(self, config: S3Config, logger: Optional[logging.Logger] = None):
        """
        Initialize S3 client.
        
        Args:
            config: S3 configuration
            logger: Optional logger instance
        """
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        
        self._client = boto3.client(
            's3',
            endpoint_url=config.endpoint,
            aws_access_key_id=config.access_key,
            aws_secret_access_key=config.secret_key,
            region_name=config.region,
            config=Config(
                signature_version='s3v4',
                s3={'addressing_style': 'path'}
            ),
            verify=config.verify_ssl
        )
    
    @property
    def client(self):
        """Return the underlying boto3 client."""
        return self._client
        
    def list_collections(self) -> list[str]:
        """
        List all collections in the attachments prefix.
        
        Returns:
            List of collection names (e.g., ['botany', 'ichthyology', 'iz'])
        """
        collections = []
        prefix = f"{self.config.prefix}/"
        
        response = self._client.list_objects_v2(
            Bucket=self.config.bucket,
            Prefix=prefix,
            Delimiter='/'
        )
        
        for common_prefix in response.get('CommonPrefixes', []):
            coll_path = common_prefix['Prefix']
            coll_name = coll_path.replace(prefix, '').rstrip('/')
            if coll_name:
                collections.append(coll_name)
                
        return collections
    
    def list_originals(
        self, 
        collection: str, 
        resume_from: Optional[str] = None
    ) -> Generator[dict, None, None]:
        """
        List all original images in a collection.
        
        Args:
            collection: Collection name
            resume_from: Optional filename to resume from (alphabetically)
            
        Yields:
            Dict with 'key', 'size', 'last_modified' for each image
        """
        originals_prefix = f"{self.config.prefix}/{collection}/originals/"
        
        paginator = self._client.get_paginator('list_objects_v2')
        page_iterator = paginator.paginate(
            Bucket=self.config.bucket,
            Prefix=originals_prefix,
        )
        
        count = 0
        yielded = 0
        for page in page_iterator:
            for obj in page.get('Contents', []):
                count += 1
                if count % 1000 == 0:
                    print(f"  Scanned {count:,} objects in {collection}/originals/ ({yielded:,} images)...")
                
                key = obj['Key']
                
                if resume_from:
                    filename = os.path.basename(key)
                    if filename < resume_from:
                        continue
                
                ext = os.path.splitext(key)[1].lower()
                if ext in self.IMAGE_EXTENSIONS:
                    yielded += 1
                    yield {
                        'key': key,
                        'size': obj['Size'],
                        'last_modified': obj['LastModified'].isoformat(),
                    }
        
        if count >= 1000:
            print(f"  Finished {collection}/originals/: {count:,} objects, {yielded:,} images")
    
    def list_thumbnails(self, collection: str) -> Generator[dict, None, None]:
        """
        List all existing thumbnails in a collection.
        
        Args:
            collection: Collection name
            
        Yields:
            Dict with 'key', 'size', 'last_modified' for each thumbnail
        """
        thumbnails_prefix = f"{self.config.prefix}/{collection}/thumbnails/"
        
        paginator = self._client.get_paginator('list_objects_v2')
        page_iterator = paginator.paginate(
            Bucket=self.config.bucket,
            Prefix=thumbnails_prefix,
        )
        
        count = 0
        yielded = 0
        for page in page_iterator:
            for obj in page.get('Contents', []):
                count += 1
                if count % 1000 == 0:
                    print(f"  Scanned {count:,} objects in {collection}/thumbnails/ ({yielded:,} images)...")
                
                key = obj['Key']
                ext = os.path.splitext(key)[1].lower()
                if ext in self.IMAGE_EXTENSIONS:
                    yielded += 1
                    yield {
                        'key': key,
                        'size': obj['Size'],
                        'last_modified': obj['LastModified'].isoformat(),
                    }
        
        if count >= 1000:
            print(f"  Finished {collection}/thumbnails/: {count:,} objects, {yielded:,} images")
    
    @staticmethod
    def get_thumbnail_key(original_key: str) -> str:
        """Convert an original image key to its thumbnail key."""
        return original_key.replace('/originals/', '/thumbnails/')
    
    @staticmethod
    def get_original_key(thumbnail_key: str) -> str:
        """Convert a thumbnail key to its original image key."""
        return thumbnail_key.replace('/thumbnails/', '/originals/')
    
    def object_exists(self, key: str) -> bool:
        """Check if an object exists in S3."""
        try:
            self._client.head_object(Bucket=self.config.bucket, Key=key)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            raise
    
    def get_object_metadata(self, key: str) -> Optional[dict]:
        """Get metadata for an S3 object."""
        try:
            response = self._client.head_object(Bucket=self.config.bucket, Key=key)
            return {
                'size': response['ContentLength'],
                'last_modified': response['LastModified'].isoformat(),
                'content_type': response.get('ContentType', 'application/octet-stream'),
            }
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return None
            raise
    
    def download_object(self, key: str) -> bytes:
        """Download an object from S3."""
        response = self._client.get_object(Bucket=self.config.bucket, Key=key)
        return response['Body'].read()
    
    def upload_object(
        self, 
        key: str, 
        data: bytes, 
        content_type: str = 'application/octet-stream'
    ) -> None:
        """Upload an object to S3."""
        self._client.put_object(
            Bucket=self.config.bucket,
            Key=key,
            Body=data,
            ContentType=content_type
        )
