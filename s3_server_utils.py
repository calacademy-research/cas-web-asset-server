"""docstring s3_server_utils.py: used to enable for s3 api compatibility for server.py.
Variables for s3 api set in docker-compose.yml as environment variables"""
import os
import shutil
import signal
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
from botocore.config import Config
from urllib.parse import quote
from bottle import HTTPResponse
from bottle import abort
import time
from functools import wraps
import settings
import threading
import atexit
import weakref
import posixpath


class S3CallTimeout(Exception):
    """Raised when an S3 operation exceeds its hard SIGALRM timeout.

    boto3's read_timeout is per-recv(), so trickle data from a stalled MinIO
    can keep the socket alive indefinitely.  SIGALRM is the only mechanism
    that can interrupt a blocking SSL read from the outside.
    Requires threads=1 in uWSGI (signal delivery targets the main thread).
    """


@contextmanager
def s3_call_timeout(seconds):
    """Hard per-call timeout using SIGALRM.

    Only arms the alarm when running in the main thread (threads=1 uWSGI).
    Falls back to a no-op in non-main threads so the code is safe to run
    in tests or with threads>1 (where boto3 read_timeout is the only guard).
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def _handler(signum, frame):
        raise S3CallTimeout(f"S3 call exceeded {seconds}s hard timeout")

    old_handler = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


class S3Connection:
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
        self._s3_lock = threading.Lock()
        self._s3_created_at = 0
        self._S3_CLIENT_MAX_AGE = 120  # seconds — recreate before MinIO closes idle connections
        atexit.register(self.cleanup_temp_folder)
        weakref.finalize(self, self.cleanup_temp_folder)


    @staticmethod
    def _close_s3_client(client):
        """Close the underlying urllib3 connection pools to prevent CLOSE-WAIT socket leaks.

        PoolManager.clear() only drops pool references without closing sockets.
        We must call close() on each connection pool to actually shut down the
        TCP connections, otherwise they linger in CLOSE-WAIT indefinitely.
        """
        try:
            http_session = client._endpoint.http_session
            manager = http_session._manager
            with manager.pools.lock:
                pools = list(manager.pools._container.values())
            for pool in pools:
                try:
                    pool.close()
                except Exception:
                    pass
            http_session.close()
        except Exception as e:
            logging.debug(f"S3 client close error (non-fatal): {e}")

    @staticmethod
    def not_found_client_error(e: ClientError) -> bool:
        try:
            status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            code = str(e.response.get("Error", {}).get("Code", "")).strip()
        except Exception:
            return False

        return (
            status == 404
            or code in {
                "404",
                "NoSuchKey",
                "NotFound",
                "NoSuchObject",
                "NoSuchVersion",
            }
        )

    @staticmethod
    def retry_s3_call(max_retries=5):
        """
        Retry decorator for S3 client initialization only.
        Retries with progressive backoff on transient errors.
        """

        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                delay = 0
                attempt = 0
                t_op_start = time.monotonic()
                while True:
                    t0 = time.monotonic()
                    try:
                        result = func(*args, **kwargs)
                        dt = round((time.monotonic() - t0) * 1000, 1)
                        if dt > 500:
                            logging.info(f"S3_OP {func.__name__} ok {dt}ms attempt={attempt+1}")
                        return result

                    except ClientError as e:
                        dt = round((time.monotonic() - t0) * 1000, 1)
                        attempt += 1
                        if attempt >= max_retries:
                            total_dt = round((time.monotonic() - t_op_start) * 1000, 1)
                            logging.error(
                                f"S3_OP {func.__name__} FAILED {total_dt}ms after {attempt} attempts: {type(e).__name__}: {e}"
                            )
                            raise
                        logging.warning(
                            f"S3_OP {func.__name__} retry {dt}ms attempt={attempt}/{max_retries}: {type(e).__name__}: {e}. "
                            f"Retrying in {delay}s..."
                        )
                        time.sleep(delay)
                        delay = min(delay + 10, 60)

                    except (EndpointConnectionError, ConnectionClosedError, ReadTimeoutError) as e:
                        dt = round((time.monotonic() - t0) * 1000, 1)
                        attempt += 1
                        if attempt >= max_retries:
                            total_dt = round((time.monotonic() - t_op_start) * 1000, 1)
                            logging.error(
                                f"S3_OP {func.__name__} FAILED {total_dt}ms after {attempt} attempts: {type(e).__name__}: {e}"
                            )
                            raise
                        logging.warning(
                            f"S3_OP {func.__name__} retry {dt}ms attempt={attempt}/{max_retries}: {type(e).__name__}: {e}. "
                            f"Retrying in {delay}s..."
                        )
                        time.sleep(delay)
                        delay = min(delay + 10, 60)

            return wrapper

        return decorator

    @staticmethod
    def s3_error_handler(func):
        """
        Decorator that converts S3 exceptions to HTTP errors.
        No retries — fail fast so the client can retry naturally.
        """
        @wraps(func)
        def wrapper(*args, **kwargs):
            t0 = time.monotonic()
            try:
                return func(*args, **kwargs)
            except S3CallTimeout as e:
                dt = round((time.monotonic() - t0) * 1000, 1)
                logging.error(f"S3_OP {func.__name__} HARD_TIMEOUT {dt}ms: {e}")
                abort(503, "S3 temporarily unavailable")
            except ClientError as e:
                dt = round((time.monotonic() - t0) * 1000, 1)
                if S3Connection.not_found_client_error(e):
                    logging.debug(f"S3_OP {func.__name__} 404 {dt}ms")
                    msg = e.response.get("Error", {}).get("Message") or "Not Found"
                    abort(404, msg)
                logging.error(f"S3_OP {func.__name__} FAILED {dt}ms: {type(e).__name__}: {e}")
                abort(503, "S3 temporarily unavailable")
            except (EndpointConnectionError, ConnectionClosedError, ReadTimeoutError) as e:
                dt = round((time.monotonic() - t0) * 1000, 1)
                logging.error(f"S3_OP {func.__name__} FAILED {dt}ms: {type(e).__name__}: {e}")
                abort(503, "S3 temporarily unavailable")
        return wrapper

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


    def _create_s3_client(self):
        """Create a new boto3 S3 client (no I/O, no locks)."""
        session = boto3.session.Session()
        return session.client(
            's3',
            endpoint_url=self.S3_ENDPOINT,
            aws_access_key_id=self.S3_ACCESS_KEY,
            aws_secret_access_key=self.S3_SECRET_KEY,
            region_name=self.S3_REGION,
            config=Config(
                max_pool_connections=4,
                retries={'max_attempts': 1, 'mode': 'standard'},
                connect_timeout=3,
                read_timeout=5,
                tcp_keepalive=True,
                signature_version='s3v4',
                s3={'use_dualstack_endpoint': False}
            )
        )

    def get_s3(self):
        """Lazy-initialized S3 client with periodic refresh to flush stale connections.

        Recycling prevents CLOSE-WAIT socket leaks: MinIO closes idle connections
        (sends FIN), but urllib3 never reads the TLS close_notify. Sockets accumulate
        in CLOSE-WAIT and hang when reused. We recycle the client (and properly close
        the old sockets) before they go stale.

        IMPORTANT: The lock only protects the pointer swap. All I/O (client creation,
        bucket validation, old client cleanup) happens outside the lock to prevent
        thread starvation — if head_bucket or close hangs, only one thread is affected.
        """
        if not self.S3_ENDPOINT:
            raise RuntimeError("S3 is not enabled")
        now = time.monotonic()
        if self._s3 is not None and (now - self._s3_created_at) < self._S3_CLIENT_MAX_AGE:
            return self._s3

        # Create new client OUTSIDE the lock (no I/O in constructor)
        client = self._create_s3_client()
        old_client = None

        with self._s3_lock:
            # Double-check — another thread may have already recycled
            if self._s3 is not None and (time.monotonic() - self._s3_created_at) < self._S3_CLIENT_MAX_AGE:
                # Another thread won the race; discard our new client
                self._close_s3_client(client)
                return self._s3
            old_client = self._s3
            self._s3 = client
            self._s3_created_at = time.monotonic()

        # All I/O happens OUTSIDE the lock
        if old_client is not None:
            self._close_s3_client(old_client)
            logging.info(f"S3 client recycled (pid={os.getpid()})")
        return client

    def s3_full_key(self, rel: str) -> str:
        """uses posixpath to create full key to avoid double slashes"""
        rel = (rel or "").lstrip("/")
        prefix = (self.S3_PREFIX or "").strip("/")
        return posixpath.join(prefix, rel) if prefix else rel

    @s3_error_handler
    def storage_exists(self, rel: str) -> bool:
        """
        Check if object exists locally or in S3.
        rel: relative path/key (no base directory).
        """
        full_key = self.s3_full_key(rel)
        if self.S3_ENDPOINT:
            key = self.s3_key(full_key)
            tid = threading.get_ident()
            t0 = time.monotonic()
            try:
                with s3_call_timeout(3):
                    self.get_s3().head_object(Bucket=self.S3_BUCKET, Key=key)
                dt = round((time.monotonic() - t0) * 1000, 1)
                if dt > 500:
                    logging.warning(f"S3_SLOW head_object SLOW tid={tid} key={key} dt={dt}ms")
                return True
            except ClientError as e:
                dt = round((time.monotonic() - t0) * 1000, 1)
                if e.response['Error']['Code'] == '404':
                    if dt > 500:
                        logging.warning(f"S3_SLOW head_object 404 SLOW tid={tid} key={key} dt={dt}ms")
                    return False
                logging.error(f"S3_ERR head_object tid={tid} key={key} dt={dt}ms error={e}")
                raise

        return False

    @s3_error_handler
    def orig_location(self, rel: str) -> str:
        """
        Validate that the original exists (S3 mode) before returning rel key/path.
        """
        if self.S3_ENDPOINT and not self.storage_exists(rel):
            abort(404, f"Missing object: {rel}")
        return rel

    @s3_error_handler
    @contextmanager
    def storage_tempfile(self, rel: str):
        """
        Yield a temp file path (under TMP_FOLDER) containing the downloaded S3 object.
        File is deleted on exit.
        """
        full_key = self.s3_full_key(rel)
        _, ext = os.path.splitext(rel)
        fd, tmp_path = tempfile.mkstemp(dir=self.TMP_FOLDER, prefix="s3dl_", suffix=ext or "")
        os.close(fd)
        try:
            t0 = time.monotonic()
            with s3_call_timeout(8):
                self.get_s3().download_file(self.S3_BUCKET, self.s3_key(full_key), tmp_path)
            dt = round((time.monotonic() - t0) * 1000, 1)
            file_size = os.path.getsize(tmp_path)
            logging.info(f"S3_DOWNLOAD key={self.s3_key(full_key)} size={file_size} bytes dt={dt}ms")
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

    @s3_error_handler
    def storage_download(self, rel: str) -> str:
        """
        downloads from S3 to a temp file and returns the local path.
        Caller is responsible for deleting tmp the file after successful execution
        to allow for resizing operations
        """
        full_key = self.s3_full_key(rel)
        _, ext = os.path.splitext(rel)
        fd, tmp_path = tempfile.mkstemp(dir=self.TMP_FOLDER, prefix="s3dl_", suffix=ext or "")
        os.close(fd)

        try:
            with s3_call_timeout(8):
                self.get_s3().download_file(self.S3_BUCKET, self.s3_key(full_key), tmp_path)
            return tmp_path
        except Exception:
            self.remove_tempfile(tmp_path)
            raise

    @s3_error_handler
    def storage_save(self, rel: str, file_object):
        """
        Save file data either to local filesystem or S3.
        file_object must be a file-like object.
        """
        full_key = self.s3_full_key(rel)
        file_object.seek(0)
        mime, _ = guess_type(full_key)
        kwargs = dict(Bucket=self.S3_BUCKET, Key=self.s3_key(full_key), Body=file_object.read())
        if mime:
            kwargs["ContentType"] = mime
        with s3_call_timeout(8):
            self.get_s3().put_object(**kwargs)

    @s3_error_handler
    def storage_delete(self, rel: str):
        """
        Delete the object referenced by rel from local filesystem or S3.
        """
        full_key = self.s3_full_key(rel)

        if self.S3_ENDPOINT:
            with s3_call_timeout(3):
                self.get_s3().delete_object(Bucket=self.S3_BUCKET, Key=self.s3_key(full_key))
            return
        abort(404)

    @s3_error_handler
    def storage_url(self, rel: str):
        """
        Generate a pre-signed URL for an S3 object if running in S3 mode. Returns None otherwise
        """
        full_key = self.s3_full_key(rel)
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

    @s3_error_handler
    def s3_stream_response(self, rel, downloadname=None, filename_for_ct=None):
        """Return a Bottle response for an S3 object.

        If settings.NGINX_S3_ACCEL is True:
          - Bottle does auth + key resolution only.
          - It returns X-Accel-Redirect to an internal Nginx (OpenResty) location.
          - Nginx streams bytes directly from MinIO, signed with SigV4 (Lua).

        Otherwise:
          - Stream through Python using boto3 (original behavior).
        """
        full_key = self.s3_full_key(rel)

        # --- Fast path: Nginx/OpenResty streams from MinIO ---
        if getattr(settings, 'NGINX_S3_ACCEL', False):
            prefix = getattr(settings, 'NGINX_S3_ACCEL_PREFIX', '/_s3_internal')
            key = self.s3_key(full_key)

            dn = downloadname or filename_for_ct or os.path.basename(full_key)
            # UTF-8 safe quoting for filenames
            dn_q = quote(os.path.basename(dn).encode('utf-8', 'replace'))

            # Note: dn/disp are used by Nginx to set headers and must NOT be forwarded to MinIO.
            internal_uri = f"{prefix}/{self.S3_BUCKET}/{key}?dn={dn_q}"
            r = HTTPResponse(status=200, body=b'')
            r.set_header('X-Accel-Redirect', internal_uri)
            return r

        # --- Slow path: stream through Python (original behavior) ---
        s3 = self.get_s3()
        with s3_call_timeout(3):
            head = s3.head_object(Bucket=self.S3_BUCKET, Key=self.s3_key(full_key))
        with s3_call_timeout(3):
            obj = s3.get_object(Bucket=self.S3_BUCKET, Key=self.s3_key(full_key))
        body = obj["Body"]  # botocore.response.StreamingBody

        mime, _ = guess_type(filename_for_ct or full_key)
        ctype = mime or head.get('ContentType', 'application/octet-stream')
        dn = downloadname or filename_for_ct or os.path.basename(full_key)
        dn_q = quote(os.path.basename(dn).encode('ascii', 'replace'))

        r = HTTPResponse(body=self.stream(body=body))
        r.set_header('Content-Type', ctype)
        r.set_header('Content-Length', str(head['ContentLength']))
        r.set_header('Content-Disposition', f"inline; filename*=utf-8''{dn_q}")
        return r