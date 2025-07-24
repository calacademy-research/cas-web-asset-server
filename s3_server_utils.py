"""docstring s3_server_utils.py: used to enable for s3 api compatibility for server.py.
Variables for s3 api set in docker-compose.yml as environment variables"""
import os
import shutil
import sys
import tempfile
from functools import lru_cache
from contextlib import contextmanager
from os import path, makedirs, remove
import logging
from mimetypes import guess_type
import boto3
from botocore.exceptions import ClientError
from urllib.parse import quote
from bottle import HTTPResponse
from bottle import abort
import time
import settings



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

            self.TMP_FOLDER = "s3_temp"
        else:
            # Provide defaults so attribute access does not fail when S3 disabled
            self.S3_ENDPOINT = self.S3_BUCKET = self.S3_ACCESS_KEY = self.S3_SECRET_KEY = self.S3_REGION = None
            self.S3_URL_EXPIRY = 0
            self.S3_PREFIX = ''
        self.chunk_size = 64 * 1024
        self.make_temp_folder()

    def make_temp_folder(self):
        """creates and cleans out folder for storage of temp images"""
        os.makedirs(self.TMP_FOLDER, exist_ok=True)

        for name in os.listdir(self.TMP_FOLDER):
            path = os.path.join(self.TMP_FOLDER, name)
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)

# --- Internal helpers ---------------------------------------------------------
    def s3_key(self, p: str) -> str:
        """Normalize a path into an S3 object key."""
        return p.lstrip('/')

    @lru_cache(maxsize=1)
    def get_s3(self):
        """Lazy-initialized singleton S3 client (only if USE_S3)."""
        if not self.S3_ENDPOINT:
            raise RuntimeError("S3 is not enabled")
        session = boto3.session.Session()
        s3 = session.client(
            's3',
            endpoint_url=self.S3_ENDPOINT,
            aws_access_key_id=self.S3_ACCESS_KEY,
            aws_secret_access_key=self.S3_SECRET_KEY,
            region_name=self.S3_REGION
        )
        # Ensure bucket exists
        try:
            s3.head_bucket(Bucket=self.S3_BUCKET)
        except ClientError as e:
            code = e.response['Error']['Code']
            if code in ('404', 'NoSuchBucket'):
                try:
                    s3.create_bucket(Bucket=self.S3_BUCKET)
                    time.sleep(10)
                    s3.head_bucket(Bucket=self.S3_BUCKET)
                except ClientError as e:
                    logging.critical(f"Bucket {self.S3_BUCKET} does not exist and could not be created.", e)
                    sys.exit()
            else:
                logging.critical(f"Bucket {self.S3_BUCKET} does not exist and could not be created.", e)
                sys.exit()
        return s3


    # --- Public storage abstraction API ------------------------------------------
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


    def orig_location(self, rel: str) -> str:
        """
        Validate that the original exists (S3 mode) before returning rel key/path.
        """
        if self.S3_ENDPOINT and not self.storage_exists(rel):
            abort(404, f"Missing object: {rel}")
        return rel


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

    def storage_download(self, rel: str) -> str:
        """
        Return a local file path to the given relative key/path. If local file
        exists, returns it; otherwise downloads from S3 to a temp file.
        """
        full_key = f"{self.S3_PREFIX}/{rel}".lstrip("/")

        if self.S3_ENDPOINT:
            tmp = tempfile.NamedTemporaryFile(delete=False)
            tmp.close()
            self.get_s3().download_file(self.S3_BUCKET, self.s3_key(full_key), tmp.name)
            return tmp.name

        abort(404)


    def storage_save(self, rel: str, file_object):
        """
        Save file data either to local filesystem or S3.
        file_object must be a file-like object.
        """
        full_key = f"{self.S3_PREFIX}/{rel}".lstrip("/")
        file_object.seek(0)
        self.get_s3().put_object(Bucket=self.S3_BUCKET, Key=self.s3_key(full_key), Body=file_object.read())


    def storage_delete(self, rel: str):
        """
        Delete the object referenced by rel from local filesystem or S3.
        """
        full_key = f"{self.S3_PREFIX}/{rel}".lstrip("/")

        if self.S3_ENDPOINT:
            self.get_s3().delete_object(Bucket=self.S3_BUCKET, Key=self.s3_key(full_key))
            return
        abort(404)


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



    def stream(self, body):
        """loads the stream by iterating through the file body by chunk size"""
        try:
            for chunk in iter(lambda: body.read(self.chunk_size), b''):
                yield chunk
        finally:
            body.close()

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
