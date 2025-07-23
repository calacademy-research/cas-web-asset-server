# s3_server_utils.py
import os
import shutil
import sys
import tempfile
from functools import lru_cache
from contextlib import contextmanager
from os import path, makedirs, remove
import logging
import socket
from urllib.parse import urlparse
import boto3
from botocore.exceptions import ClientError
from bottle import abort
import time
import settings

if os.getenv('S3_ENDPOINT'):
    S3_ENDPOINT   = os.getenv('S3_ENDPOINT')
    S3_BUCKET     = os.getenv('S3_BUCKET')
    S3_ACCESS_KEY = os.getenv('S3_ACCESS_KEY')
    S3_SECRET_KEY = os.getenv('S3_SECRET_KEY')
    S3_URL_EXPIRY = int(os.getenv('S3_URL_EXPIRY', '3600'))
    S3_REGION     = os.getenv('S3_REGION')
    TMP_FOLDER = "s3_temp"

    if os.path.isdir(TMP_FOLDER):
        # clearing out any temp undeleted temp files on startup
        shutil.rmtree(TMP_FOLDER)
    os.makedirs(TMP_FOLDER, exist_ok=True)
else:
    # Provide defaults so attribute access does not fail when S3 disabled
    S3_ENDPOINT = S3_BUCKET = S3_ACCESS_KEY = S3_SECRET_KEY = S3_REGION = None
    S3_URL_EXPIRY = 0


# --- Internal helpers ---------------------------------------------------------
def s3_key(p: str) -> str:
    """Normalize a path into an S3 object key."""
    return p.lstrip('/')

@lru_cache(maxsize=1)
def get_s3():
    """Lazy-initialized singleton S3 client (only if USE_S3)."""
    if not S3_ENDPOINT:
        raise RuntimeError("S3 is not enabled")
    session = boto3.session.Session()
    s3 = session.client(
        's3',
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name=S3_REGION
    )
    # Ensure bucket exists
    try:
        s3.head_bucket(Bucket=S3_BUCKET)
    except ClientError as e:
        code = e.response['Error']['Code']
        if code in ('404', 'NoSuchBucket'):
            try:
                s3.create_bucket(Bucket=S3_BUCKET)
                time.sleep(10)
                s3.head_bucket(Bucket=S3_BUCKET)
            except ClientError as e:
                logging.critical(f"Bucket {S3_BUCKET} does not exist and could not be created.", e)
                sys.exit()
        else:
            logging.critical(f"Bucket {S3_BUCKET} does not exist and could not be created.", e)
            sys.exit()
    return s3


# --- Public storage abstraction API ------------------------------------------
def storage_exists(rel: str) -> bool:
    """
    Check if object exists locally or in S3.
    rel: relative path/key (no base directory).
    """
    local_path = os.path.join(settings.BASE_DIR, rel)
    if path.exists(local_path):
        return True
    if S3_ENDPOINT:
        try:
            get_s3().head_object(Bucket=S3_BUCKET, Key=s3_key(rel))
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            raise
    return False


def orig_location(rel: str) -> str:
    """
    Validate that the original exists (S3 mode) before returning rel key/path.
    """
    if S3_ENDPOINT and not storage_exists(rel):
        abort(404, f"Missing object: {rel}")
    return rel


@contextmanager
def storage_tempfile(rel: str):
    """
    Yield a temp file path (under TMP_FOLDER) containing the downloaded S3 object.
    File is deleted on exit.
    """
    _, ext = os.path.splitext(rel)
    fd, tmp_path = tempfile.mkstemp(dir=TMP_FOLDER, prefix="s3dl_", suffix=ext or "")
    os.close(fd)
    try:
        get_s3().download_file(S3_BUCKET, s3_key(rel), tmp_path)
        yield tmp_path
    finally:
        remove_tempfile(tmp_path)

def remove_tempfile(tmp_path: str):
    """
    removes temp-files created by the storage download with exception
    """
    tmp_path = os.path.join(tmp_path)
    if os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
        except OSError as e:
            logging.warning(f"Could not delete {tmp_path}: {e}")

def storage_download(rel: str) -> str:
    """
    Return a local file path to the given relative key/path. If local file
    exists, returns it; otherwise downloads from S3 to a temp file.
    """
    local = path.join(settings.BASE_DIR, rel)
    if path.exists(local):
        return local
    if S3_ENDPOINT:
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.close()
        get_s3().download_file(S3_BUCKET, s3_key(rel), tmp.name)
        return tmp.name
    abort(404)


def storage_save(rel: str, file_object):
    """
    Save file data either to local filesystem or S3.
    file_object must be a file-like object.
    """
    local = path.join(settings.BASE_DIR, rel)
    local_dir = path.dirname(local)
    # If local mode OR destination directory already exists locally, save local
    if path.isdir(local_dir) or not S3_ENDPOINT:
        makedirs(local_dir, exist_ok=True)
        with open(local, 'wb') as o:
            o.write(file_object.read())
        return
    # S3
    file_object.seek(0)
    get_s3().put_object(Bucket=S3_BUCKET, Key=s3_key(rel), Body=file_object.read())


def storage_delete(rel: str):
    """
    Delete the object referenced by rel from local filesystem or S3.
    """
    local = path.join(settings.BASE_DIR, rel)
    if path.exists(local):
        remove(local)
        return
    if S3_ENDPOINT:
        get_s3().delete_object(Bucket=S3_BUCKET, Key=s3_key(rel))
        return
    abort(404)


def storage_url(rel: str):
    """
    Generate a presigned URL for an S3 object if running in S3 mode and the
    object is not found locally. Returns None for local files.
    """
    local = path.join(settings.BASE_DIR, rel)
    if path.exists(local):
        return None
    if S3_ENDPOINT:
        return get_s3().generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET, 'Key': s3_key(rel)},
            ExpiresIn=S3_URL_EXPIRY
        )
    return None
