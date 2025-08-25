"""docstring s3_server_utils.py: used to enable for s3 api compatibility for server.py.
Variables for s3 api set in docker-compose.yml as environment variables"""
import os
import shutil
import sys
import tempfile
import uuid
from functools import lru_cache
from contextlib import contextmanager
from os import path, makedirs, remove
import logging
from mimetypes import guess_type
import boto3
from botocore.exceptions import ClientError, EndpointConnectionError, ConnectionClosedError, ReadTimeoutError
from urllib.parse import quote
from bottle import HTTPResponse
from bottle import abort
import time
from functools import wraps
import settings
import threading
import atexit
import weakref

class S3Connection():
    def __init__(self):
        mount_path = '/code/attachments'
        if os.getenv('S3_ENDPOINT') and not os.path.ismount(mount_path):
            self.S3_ENDPOINT   = os.getenv('S3_ENDPOINT')
            self.S3_BUCKET     = os.getenv('S3_BUCKET')
            self.S3_PREFIX     = os.getenv('S3_PREFIX', '')
            self.S3_ACCESS_KEY = os.getenv('S3_ACCESS_KEY')
            self.S3_SECRET_KEY = os.getenv('S3_SECRET_KEY')
            self.S3_URL_EXPIRY = int(os.getenv('S3_URL_EXPIRY', '3600'))
            self.S3_REGION     = os.getenv('S3_REGION')
            self.cleanup_temp_folder()
            unique_id = f"{os.getpid()}-{threading.get_ident()}-{uuid.uuid4()}"
            self.TMP_FOLDER = path.join("s3_temp", unique_id)
            os.makedirs(self.TMP_FOLDER, exist_ok=True)

        else:
            self.S3_ENDPOINT = self.S3_BUCKET = self.S3_ACCESS_KEY = self.S3_SECRET_KEY = self.S3_REGION = None
            self.S3_URL_EXPIRY = 0
            self.S3_PREFIX = ''
            self.cleanup_temp_folder()

        self.chunk_size = 64 * 1024
        self._s3 = None
        atexit.register(self.cleanup_temp_folder)
        weakref.finalize(self, self.cleanup_temp_folder)

    @staticmethod
    def retry_s3_call():
        """
        Retry decorator for S3 operations with progressive backoff and infinite retries after 60s.
        """

        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                delay = 0
                attempt = 0
                while True:
                    try:
                        return func(*args, **kwargs)
                    except (ClientError, EndpointConnectionError, ConnectionClosedError, ReadTimeoutError) as e:
                        attempt += 1
                        logging.warning(
                            f"[{func.__name__}] Attempt {attempt} failed: {type(e).__name__}: {e}. Retrying in {delay}s..."
                        )
                        time.sleep(delay)
                        delay = min(delay + 10, 60)

            return wrapper

        return decorator

    def cleanup_temp_folder(self):
        """Remove this instance's TMP_FOLDER and stale s3_temp folders safely."""
        try:
            if hasattr(self, 'TMP_FOLDER') and os.path.isdir(self.TMP_FOLDER):
                shutil.rmtree(self.TMP_FOLDER)
                logging.info(f"Cleaned up own temp folder: {self.TMP_FOLDER}")
        except Exception as e:
            logging.warning(f"Failed to clean own TMP_FOLDER: {e}")
        try:
            base_folder = "s3_temp"
            now = time.time()
            max_age = 2 * int(getattr(self, 'S3_URL_EXPIRY', 3600))

            if os.path.isdir(base_folder):
                for name in os.listdir(base_folder):
                    full_path = os.path.join(base_folder, name)
                    if full_path == getattr(self, 'TMP_FOLDER', None):
                        continue
                    try:
                        age = now - os.path.getmtime(full_path)
                        if age > max_age and os.path.isdir(full_path):
                            shutil.rmtree(full_path)
                            logging.info(f"Cleaned old temp folder: {full_path}")
                    except FileNotFoundError:
                        continue
                    except Exception as e:
                        logging.warning(f"Could not clean temp folder {full_path}: {e}")
        except Exception as e:
            logging.warning(f"Global cleanup failed: {e}")


    def s3_key(self, p: str) -> str:
        """Normalize a path into an S3 object key."""
        return p.lstrip('/')


    @retry_s3_call()
    def get_s3(self):
        """Lazy-initialized singleton S3 client (only if USE_S3)."""
        if not self.S3_ENDPOINT:
            raise RuntimeError("S3 is not enabled")
        if not hasattr(self, "_s3") or self._s3 is None:
            session = boto3.session.Session()
            self._s3 = session.client(
                's3',
                endpoint_url=self.S3_ENDPOINT,
                aws_access_key_id=self.S3_ACCESS_KEY,
                aws_secret_access_key=self.S3_SECRET_KEY,
                region_name=self.S3_REGION
            )
            # Ensure bucket exists
            try:
                self._s3.head_bucket(Bucket=self.S3_BUCKET)
            except ClientError as e:
                code = e.response['Error']['Code']
                if code in ('404', 'NoSuchBucket'):
                    try:
                        self._s3.create_bucket(Bucket=self.S3_BUCKET)
                        time.sleep(10)
                        self._s3.head_bucket(Bucket=self.S3_BUCKET)
                    except ClientError as e:
                        logging.critical(f"Bucket {self.S3_BUCKET} does not exist and could not be created.", e)
                        raise
                else:
                    logging.critical(f"Bucket {self.S3_BUCKET} does not exist and could not be created.", e)
                    raise
        return self._s3

    @retry_s3_call()
    def storage_exists(self, rel: str) -> bool:
        """
        Check if object exists locally or in S3.
        rel: relative path/key (no base directory).
        """
        full_key = f"{self.S3_PREFIX}/{rel}".lstrip("/")
        if self.S3_ENDPOINT:
            try:
                self.get_s3().head_object(Bucket=self.S3_BUCKET, Key=self.s3_key(full_key))
                return True
            except ClientError as e:
                if e.response['Error']['Code'] == '404':
                    return False
                raise

        return False

    @retry_s3_call()
    def orig_location(self, rel: str) -> str:
        """
        Validate that the original exists (S3 mode) before returning rel key/path.
        """
        if self.S3_ENDPOINT and not self.storage_exists(rel):
            abort(404, f"Missing object: {rel}")
        return rel

    @retry_s3_call()
    @contextmanager
    def storage_tempfile(self, rel: str):
        """
        Yield a temp file path (under TMP_FOLDER) containing the downloaded S3 object.
        File is deleted on exit.
        """
        full_key = f"{self.S3_PREFIX}/{rel}".lstrip("/")
        _, ext = os.path.splitext(rel)
        fd, tmp_path = tempfile.mkstemp(dir=self.TMP_FOLDER, prefix="s3dl_", suffix=ext or "")
        os.close(fd)
        try:
            self.get_s3().download_file(self.S3_BUCKET, self.s3_key(full_key), tmp_path)
            yield tmp_path
        finally:
            self.remove_tempfile(tmp_path)

    @retry_s3_call()
    def remove_tempfile(self, tmp_path: str):
        """
        removes temp-files created by the storage download with exception
        """
        tmp_path = os.path.join(tmp_path)
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError as e:
                logging.warning(f"Could not delete {tmp_path}: {e}")

    @retry_s3_call()
    def storage_download(self, rel: str) -> str:
        """
        downloads from S3 to a temp file and returns the local path.
        Caller is responsible for deleting the file (use remove_tempfile).
        """
        full_key = f"{self.S3_PREFIX}/{rel}".lstrip("/")
        _, ext = os.path.splitext(rel)
        fd, tmp_path = tempfile.mkstemp(dir=self.TMP_FOLDER, prefix="s3dl_", suffix=ext or "")
        os.close(fd)

        try:
            self.get_s3().download_file(self.S3_BUCKET, self.s3_key(full_key), tmp_path)
            return tmp_path
        except Exception:
            self.remove_tempfile(tmp_path)
            raise

    @retry_s3_call()
    def storage_save(self, rel: str, file_object):
        """
        Save file data either to local filesystem or S3.
        file_object must be a file-like object.
        """
        full_key = f"{self.S3_PREFIX}/{rel}".lstrip("/")
        file_object.seek(0)
        self.get_s3().put_object(Bucket=self.S3_BUCKET, Key=self.s3_key(full_key), Body=file_object.read())

    @retry_s3_call()
    def storage_delete(self, rel: str):
        """
        Delete the object referenced by rel from local filesystem or S3.
        """
        full_key = f"{self.S3_PREFIX}/{rel}".lstrip("/")

        if self.S3_ENDPOINT:
            self.get_s3().delete_object(Bucket=self.S3_BUCKET, Key=self.s3_key(full_key))
            return
        abort(404)

    @retry_s3_call()
    def storage_url(self, rel: str):
        """
        Generate a pre-signed URL for an S3 object if running in S3 mode. Returns None otherwise
        """
        full_key = f"{self.S3_PREFIX}/{rel}".lstrip("/")
        if self.S3_ENDPOINT:
            return self.get_s3().generate_presigned_url(
                'get_object',
                Params={'Bucket': self.S3_BUCKET, 'Key': self.s3_key(full_key)},
                ExpiresIn=self.S3_URL_EXPIRY
            )
        return None

    @retry_s3_call()
    def stream(self, body):
        """loads the stream by iterating through the file body by chunk size"""
        try:
            for chunk in iter(lambda: body.read(self.chunk_size), b''):
                yield chunk
        finally:
            body.close()

    @retry_s3_call()
    def s3_stream_response(self, key, downloadname=None, filename_for_ct=None):
        """streams s3 response, allowing for no static storage usage."""
        full_key = f"{self.S3_PREFIX}/{key}".lstrip("/")
        s3 = self.get_s3()
        head = s3.head_object(Bucket=self.S3_BUCKET, Key=self.s3_key(full_key))
        obj = s3.get_object(Bucket=self.S3_BUCKET, Key=self.s3_key(full_key))
        body = obj["Body"]  # botocore.response.StreamingBody

        mime, _ = guess_type(filename_for_ct or full_key)
        ctype = mime or head.get('ContentType', 'application/octet-stream')
        # Inline unless caller asked for a download name
        dn = downloadname or filename_for_ct or os.path.basename(full_key)
        dn_q = quote(os.path.basename(dn).encode('ascii', 'replace'))

        r = HTTPResponse(body=self.stream(body=body))
        r.set_header('Content-Type', ctype)
        r.set_header('Content-Length', str(head['ContentLength']))
        r.set_header('Content-Disposition', f"inline; filename*=utf-8''{dn_q}")
        return r
