import logging
import os
import shutil
import signal
import sys
import faulthandler
import time
import tempfile
import threading
import uuid
import resource
from contextlib import contextmanager
from functools import wraps
from glob import glob
from mimetypes import guess_type
from os import makedirs, path, remove
from urllib.parse import quote
from urllib.request import pathname2url
import hmac
import json
from collection_definitions import COLLECTION_DIRS
from datetime import datetime
from time import sleep
from cas_metadata_tools import MetadataTools
import subprocess
from bottle import Bottle
from image_db import ImageDb
from image_db import TIME_FORMAT
from urllib.parse import unquote
from s3_server_utils import S3Connection, s3_call_timeout, S3CallTimeout
from image_cache import (
    cache_get_by_internal_filename,
    cache_get_by_pattern,
    invalidate_cache,
    CACHE_DB_PATH,
    CACHE_INVALIDATE_PATH,
)

# Phase 6: crash forensics — dump Python tracebacks on SIGSEGV/SIGABRT
faulthandler.enable(file=sys.stderr, all_threads=True)
try:
    faulthandler.register(signal.SIGUSR1, file=sys.stderr, all_threads=True)
except (OSError, AttributeError):
    pass  # SIGUSR1 not available on all platforms

app = application = Bottle()


class DbCallTimeout(Exception):
    """Raised when a database operation exceeds its hard SIGALRM timeout."""


@contextmanager
def db_call_timeout(seconds):
    """Hard per-call timeout for DB operations using SIGALRM.

    Same mechanism as s3_call_timeout — only arms in main thread (threads=1).
    Prevents MySQL queries from hanging until harakiri when the DB is slow
    (NFS contention, lock waits, network stalls).
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def _handler(signum, frame):
        raise DbCallTimeout(f"DB call exceeded {seconds}s hard timeout")

    old_handler = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)

# initializing s3 connection
s3_conn = S3Connection()

# Configure logging
import settings

level = logging.getLevelName(settings.LOG_LEVEL)
logging.basicConfig(stream=sys.stdout, level=level)

from bottle import (
    Response, BaseRequest, request, response, static_file, template, abort,
    HTTPResponse)

BaseRequest.MEMFILE_MAX = 300 * 1024 * 1024

_server_start_time = time.monotonic()

# Singleton ImageDb instance - pool handles connections
_image_db = None

def get_image_db():
    global _image_db
    if _image_db is None:
        _image_db = ImageDb()
    return _image_db


class RequestTracer:
    """Bottle plugin: wraps every request with timing, unique ID, and structured JSON logging."""
    name = 'request_tracer'
    api = 2

    def apply(self, callback, route):
        def wrapper(*args, **kwargs):
            req_id = request.headers.get('X-Request-Id', str(uuid.uuid4())[:8])
            request.trace = {
                'req_id': req_id,
                'method': request.method,
                'path': request.path,
                'query': dict(request.query),
                't_start': time.monotonic(),
                'stages': [],
                'pid': os.getpid(),
                'tid': threading.get_ident(),
            }
            try:
                result = callback(*args, **kwargs)
                request.trace['status'] = response.status_code
                return result
            except HTTPResponse as e:
                request.trace['status'] = e.status_code
                raise
            except Exception as e:
                request.trace['status'] = 500
                request.trace['error'] = f"{type(e).__name__}: {e}"
                raise
            finally:
                request.trace['t_total_ms'] = round(
                    (time.monotonic() - request.trace['t_start']) * 1000, 1
                )
                # Only log non-trivial requests (skip GET / which is noisy)
                if request.trace.get('t_total_ms', 0) > 100 or request.path != '/':
                    logging.info("REQ_TRACE " + json.dumps(request.trace, default=str))
        return wrapper

app.install(RequestTracer())


@contextmanager
def trace_stage(name):
    """Add a timed stage to the current request trace."""
    t0 = time.monotonic()
    try:
        yield
    finally:
        dt = round((time.monotonic() - t0) * 1000, 1)
        try:
            request.trace['stages'].append((name, dt))
        except (AttributeError, KeyError):
            pass


def log(msg):
    logging.debug(msg)


def get_rel_path(coll, thumb_p, storename):
    """Return originals or thumbnails subdirectory of the main
    attachments directory for the given collection.
    """
    type_dir = settings.THUMB_DIR if thumb_p else settings.ORIG_DIR
    first_subdir = storename[0:2]
    second_subdir = storename[2:4]
    if COLLECTION_DIRS is None:
        return path.join(type_dir, first_subdir, second_subdir)

    try:
        coll_dir = COLLECTION_DIRS[coll]
    except KeyError:
        err = f"Unknown collection: {coll}"
        log(err)
        abort(404, "Unknown collection: %r" % coll)

    return path.join(coll_dir, type_dir, first_subdir, second_subdir)


def str2bool(value, raise_exc=False):
    """converts diverse string values into boolean True or False,
       replaces deprecated distutils and str2bool."""
    true_set = {'yes', 'true', 't', 'y', '1'}
    false_set = {'no', 'false', 'f', 'n', '0'}

    if isinstance(value, str):
        value = value.lower()
        if value in true_set:
            return True
        if value in false_set:
            return False

    if raise_exc:
        raise ValueError('Expected "%s"' % '", "'.join(true_set | false_set))
    return None


def generate_token(timestamp, filename):
    """Generate the auth token for the given filename and timestamp.
    This is for comparing to the client submitted token.
    """
    timestamp = str(timestamp)
    if timestamp is None:
        log(f"Missing timestamp; token generation failure.")
    if filename is None:
        log(f"Missing filename, token generation failure.")
    mac = hmac.new(settings.KEY.encode(), timestamp.encode() + filename.encode(), digestmod='md5')
    return ':'.join((mac.hexdigest(), timestamp))


class TokenException(Exception):
    """Raised when an auth token is invalid for some reason."""
    pass


def get_timestamp():
    """Return an integer timestamp with one second resolution for
    the current moment.
    """
    return int(time.time())


def validate_token(token_in, filename):
    """Validate the input token for given filename using the secret key
    in settings. Checks that the token is within the time tolerance and
    is valid.
    """
    if settings.KEY is None:
        return
    if token_in == '':
        raise TokenException("Auth token is missing.")
    if ':' not in token_in:
        raise TokenException("Auth token is malformed.")

    mac_in, timestr = token_in.split(':')
    try:
        timestamp = int(timestr)
    except ValueError:
        raise TokenException("Auth token is malformed.")

    if settings.TIME_TOLERANCE is not None:
        current_time = get_timestamp()
        if not abs(current_time - timestamp) < settings.TIME_TOLERANCE:
            raise TokenException("Auth token timestamp out of range: %s vs %s" % (timestamp, current_time))

    if token_in != generate_token(timestamp, filename):
        raise TokenException("Auth token is invalid.")
    log(f"Valid token: {token_in} time: {timestr}")


def require_token(filename_param, always=False):
    """Decorate a view function to require an auth token to be present for access.
    filename_param defines the field in the request that contains the filename
    against which the token should validate.
    If REQUIRE_KEY_FOR_GET is False, validation will be skipped for GET and HEAD
    requests.
    Automatically adds the X-Timestamp header to responses to help clients stay
    syncronized.
    """
    def decorator(func):
        @include_timestamp
        @wraps(func)
        def wrapper(*args, **kwargs):
            if always or request.method not in ('GET', 'HEAD') or settings.REQUIRE_KEY_FOR_GET:
                params = request.forms if request.method == 'POST' else request.query
                try:
                    validate_token(params.token, params.get(filename_param))
                except TokenException as e:
                    response.content_type = 'text/plain; charset=utf-8'
                    response.status = 403
                    response.body = f"403 - forbidden. Invalid token: '{params.token}'"
                    log(response.body)
                    return response
            return func(*args, **kwargs)
        return wrapper
    return decorator


def include_timestamp(func):
    """Decorate a view function to include the X-Timestamp header to help clients
    maintain time synchronization.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        (result if isinstance(result, Response) else response) \
            .set_header('X-Timestamp', str(get_timestamp()))
        return result
    return wrapper


def allow_cross_origin(func):
    """Decorate a view function to allow cross domain access."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
        except HTTPResponse as r:
            r.set_header('Access-Control-Allow-Origin', '*')
            raise
        (result if isinstance(result, Response) else response) \
            .set_header('Access-Control-Allow-Origin', '*')
        return result
    return wrapper


def _check_deadline(deadline):
    """Abort with 503 if the request deadline has passed."""
    if time.monotonic() > deadline:
        logging.warning("REQUEST_DEADLINE exceeded, aborting before harakiri")
        abort(503, "Request timeout")


# Budget must be well under harakiri (20s) so we abort cleanly
_RESOLVE_DEADLINE_S = 15


def resolve_file(filename, collection, type, scale):
    """Inspect the request object to determine the file being requested.
    If the request is for a thumbnail , and it has not been generated, do
    so before returning accession_copy.
    Returns the relative path to the requested file in the base attachments directory.
    """
    deadline = time.monotonic() + _RESOLVE_DEADLINE_S
    thumb_p = (type == "T")
    storename = filename
    relpath = get_rel_path(collection, thumb_p, storename)
    file_path = os.path.join(relpath, storename)

    if not thumb_p:
        with trace_stage('orig_location'):
            return s3_conn.orig_location(file_path)

    scale = int(scale) if scale else 200
    mimetype, encoding = guess_type(storename)
    assert mimetype in settings.CAN_THUMBNAIL

    root, ext = os.path.splitext(storename)
    if mimetype in ('application/pdf', 'image/tiff'):
        ext = '.png'

    scaled_name = f"{root}_{scale}{ext}"
    rel_thumb = os.path.join(relpath, scaled_name)

    if s3_conn.S3_ENDPOINT:
        with trace_stage('s3_exists_thumb'):
            if s3_conn.storage_exists(rel_thumb):
                log("Serving previously scaled thumbnail from S3")
                return rel_thumb
    else:
        local_thumb = os.path.join(settings.BASE_DIR, rel_thumb)
        if os.path.exists(local_thumb):
            log("Serving previously scaled thumbnail")
            return rel_thumb
        basepath = os.path.join(settings.BASE_DIR, relpath)
        os.makedirs(basepath, exist_ok=True)

    if s3_conn.S3_ENDPOINT:
        orig_key = os.path.join(get_rel_path(collection, False, storename), storename)

        _check_deadline(deadline)
        with trace_stage('s3_exists_orig'):
            if not s3_conn.storage_exists(orig_key):
                abort(404, f"Missing object: {orig_key}")

        _check_deadline(deadline)
        # Context-managed download ensures the temp file is deleted after use
        with trace_stage('s3_download'):
            with s3_conn.storage_tempfile(orig_key) as input_path:
                try:
                    request.trace['file_size_bytes'] = os.path.getsize(input_path)
                except (AttributeError, KeyError):
                    pass

                _check_deadline(deadline)
                convert_args = ['-resize', f"{scale}x{scale}>"]
                convert_input = input_path
                if mimetype == 'application/pdf':
                    convert_input = f"{input_path}[0]"
                    convert_args.extend(['-background', 'white', '-flatten'])

                tmp_out = tempfile.NamedTemporaryFile(delete=False, suffix=ext).name
                with trace_stage('imagemagick_convert'):
                    result = subprocess.run(
                        ["convert", convert_input] + convert_args + [tmp_out],
                        check=True, timeout=30, close_fds=False,
                        capture_output=True
                    )
                    if result.stderr:
                        logging.warning(f"CONVERT_STDERR: {result.stderr.decode('utf-8', errors='replace')[:500]}")

                _check_deadline(deadline)
                try:
                    with trace_stage('s3_upload_thumb'):
                        with open(tmp_out, 'rb') as f:
                            s3_conn.storage_save(rel_thumb, f)
                finally:
                    s3_conn.remove_tempfile(tmp_out)

        return rel_thumb
    else:
        orig_dir = os.path.join(
            settings.BASE_DIR,
            get_rel_path(collection, False, storename)
        )
        input_path = os.path.join(orig_dir, storename)
        if not os.path.exists(input_path):
            abort(404, f"Missing original: {input_path}")

    convert_args = ['-resize', f"{scale}x{scale}>"]
    if mimetype == 'application/pdf':
        input_path += '[0]'
        convert_args.extend(['-background', 'white', '-flatten'])

    tmp_out = tempfile.NamedTemporaryFile(delete=False, suffix=ext).name
    subprocess.run(["convert", input_path] + convert_args + [tmp_out], check=True, timeout=30, close_fds=False)

    final_path = os.path.join(settings.BASE_DIR, rel_thumb)
    # using shutil to account for mounted filesystem
    shutil.move(tmp_out, final_path)

    return rel_thumb

@app.route('/static/<path:path>')
def static(path):
    """Serve static files to the client. Primarily for Web Portal."""
    if not settings.ALLOW_STATIC_FILE_ACCESS:
        abort(404)
    filename = path.split('/')[-1]
    image_db = get_image_db()
    records = cache_get_by_internal_filename(filename)
    if records is None:
        try:
            with db_call_timeout(5):
                records = image_db.get_image_record_by_internal_filename(filename)
        except DbCallTimeout:
            logging.error(f"DB_TIMEOUT static filename={filename}")
            abort(503, "Database temporarily unavailable")
    if len(records) < 1:
        log(f"Static record not found: {request.query.filename}")
        response.content_type = 'text/plain; charset=utf-8'
        response.status = 404
        return response
    if records[0]['redacted']:
        response.content_type = 'text/plain; charset=utf-8'
        response.status = 403
        log(f"Token required")
        return response

    if s3_conn.S3_ENDPOINT:
        return s3_conn.s3_stream_response(
                    rel=path,
                    filename_for_ct=filename,
                    downloadname=None
                                           )


    return static_file(path, root=settings.BASE_DIR)


def getFileUrl(filename, collection, file_type, scale, override_url=False):
    """getFileUrl: creates server url for images.
        params:
            filename: name of file to create url for
            collection: the scientific collection that the image is part of.
            file_type: file, jpg, tif, pdf
            scale: the scale to save the file or image. 0 is original size.
            override_url: used override the sever name variable for a custom public server name
     """
    if override_url:
        server_name = f"{settings.PUBLIC_SERVER}:{settings.PUBLIC_SERVER_PORT}"
        protocol = settings.PUBLIC_SERVER_PROTOCOL
    else:
        server_name = f"{settings.SERVER_NAME}:{settings.SERVER_PORT}" if settings.OVERRIDE_PORT else settings.SERVER_NAME
        protocol = settings.SERVER_PROTOCOL

    return '%s://%s/static/%s' % (
        protocol,
        server_name,
        pathname2url(resolve_file(filename, collection, file_type, scale))
    )


@app.route('/getfileref')
@allow_cross_origin
def getfileref():
    """Returns a URL to the static file indicated by the query parameters."""
    if not settings.ALLOW_STATIC_FILE_ACCESS:
        log("static file access denied")
        abort(404)
    response.content_type = 'text/plain; charset=utf-8'
    return getFileUrl(
        request.query.filename,
        request.query.coll,
        request.query['type'],
        request.query.scale,
        settings.INTERNAL
    )


@app.route('/fileget')
@require_token('filename')
def fileget():
    """Returns the file data of the file indicated by the query parameters."""
    log(f"fileget {request.query.filename}")
    image_db = get_image_db()
    with trace_stage('db_lookup'):
        records = cache_get_by_internal_filename(request.query.filename)
        if records is None:
            try:
                with db_call_timeout(5):
                    records = image_db.get_image_record_by_internal_filename(request.query.filename)
            except DbCallTimeout:
                logging.error(f"DB_TIMEOUT fileget db_lookup filename={request.query.filename}")
                abort(503, "Database temporarily unavailable")
    log("Fileget complete")
    if len(records) < 1:
        log(f"Record not found: {request.query.filename}")
        response.content_type = 'text/plain; charset=utf-8'
        response.status = 404
        return response

    if records[0]['redacted']:
        log("Redacted, check auth token")
        try:
            # Note, we're hitting this twice with the @require_token decorator
            validate_token(request.query.token, request.query.filename)
        except TokenException as e:
            response.content_type = 'text/plain; charset=utf-8'
            response.status = 403
            response.body = f"403 - forbidden. Invalid token: '{request.query.token}'"
            log(response.body)
            return response
        log("Token validated for redacted record...")
    else:
        log("Not redacted, no check required")

    log(f"Valid request: {request.query.filename}")
    resolved = resolve_file(
        request.query.filename,
        request.query.coll,
        request.query['type'],
        request.query.scale
    )

    if s3_conn.S3_ENDPOINT:
        return s3_conn.s3_stream_response(
            rel=resolved,
            filename_for_ct=request.query.filename,
            downloadname=request.query.get('downloadname')
        )

    # fallback to local filesystem
    r = static_file(resolved, root=settings.BASE_DIR)
    download_name = request.query.downloadname
    if download_name:
        dn = quote(path.basename(download_name).encode('ascii','replace'))
        r.set_header('Content-Disposition', f"inline; filename*=utf-8''{dn}")
    log(f"Get complete (FS): {request.query.filename}")
    return r


@app.route('/fileupload', method='OPTIONS')
@allow_cross_origin
def fileupload_options():
    response.content_type = "text/plain; charset=utf-8"
    return ''


@app.route('/fileupload', method='POST')
@allow_cross_origin
@require_token('store')
def fileupload():
    """Accept original file uploads and store them in the proper
    attachment subdirectory.
    """
    image_db = get_image_db()
    start_save = time.time()
    log("Post request for fileupload...")
    thumb_p = (request.forms['type'] == "T")
    storename = request.forms.store
    basepath = path.join(
        settings.BASE_DIR,
        get_rel_path(request.forms.coll, thumb_p, storename)
    )
    pathname = path.join(basepath, storename)

    # Basic validation
    if len(storename) < 7:
        log(f"Name too short: {storename}")
        response.content_type = 'text/plain; charset=utf-8'
        response.status = 400
        return response
    if thumb_p:
        return 'Ignoring thumbnail upload!'

    # Check for duplicates by original_path in DB
    try:
        with db_call_timeout(5):
            if 'original_path' in request.forms:
                response_list = image_db.get_image_record_by_original_path(
                    original_path=request.forms['original_path'],
                    collection=request.forms.coll,
                    exact=True
                )
            else:
                response_list = []
    except DbCallTimeout:
        logging.error(f"DB_TIMEOUT fileupload duplicate_check")
        abort(503, "Database temporarily unavailable")

    upload = list(request.files.values())[0]
    log(f"Saving upload: {upload}")

    # gets replaced with check if s3_conn.S3_ENDPOINT is true
    s3_exists = False
    key = None
    if s3_conn.S3_ENDPOINT:
        try:
            key = path.join(
                get_rel_path(request.forms.coll, thumb_p, storename),
                storename
            )
            resp = s3_conn.get_s3().list_objects_v2(Bucket=s3_conn.S3_BUCKET, Prefix=key)
            s3_exists = bool(resp.get('Contents'))
        except Exception as e:
            log(f"S3 list_objects_v2 error: {e}")
            abort(500, f"S3 error: {e}")

    # Unified duplicate check
    if s3_exists or path.isfile(pathname) or len(response_list) > 0:
        log("Duplicate file detected; returning 409")
        response.content_type = 'text/plain; charset=utf-8'
        response.status = 409
        return response

    # Save the upload
    if s3_conn.S3_ENDPOINT and key:
        s3_conn.storage_save(key, upload.file)
    else:
        if not path.exists(basepath):
            makedirs(basepath)
        upload.save(pathname, overwrite=True)

    # Prepare metadata for DB record
    response.content_type = 'text/plain; charset=utf-8'
    original_filename = None
    original_path = None
    notes = None
    redacted = False
    orig_md5 = None
    datetime_now = datetime.utcnow()

    if 'original_filename' in request.forms:
        log("original filename field set")
        original_filename = request.forms['original_filename']
    else:
        notes = f"uploaded manually through specify portal at {datetime_now}"
        log("original filename field is not set")

    if 'original_path' in request.forms:
        original_path = request.forms['original_path']
    if 'notes' in request.forms:
        notes = request.forms['notes']
    if 'redacted' in request.forms:
        redacted = str2bool(request.forms['redacted'])
    if 'datetime' in request.forms:
        datetime_now = datetime.strptime(request.forms['datetime'], TIME_FORMAT)
    if 'orig_md5' in request.forms:
        orig_md5 = request.forms['orig_md5']

    # Create the DB record
    try:
        image_db.create_image_record(
            original_filename,
            getFileUrl(storename, request.forms.coll, 'file', 0, settings.INTERNAL),
            storename,
            request.forms.coll,
            original_path,
            notes,
            redacted,
            datetime_now,
            orig_md5
        )
    except Exception as ex:
        print(f"Unexpected error: {ex}")
        abort(500, f'Unexpected error: {ex}')

    invalidate_cache()
    log(f"Image upload complete: original filename {original_filename} mapped to {storename}")
    end_save = time.time()
    log(f"Total time: {end_save - start_save}")
    return 'Ok.'


@app.route('/filedelete', method='POST')
@require_token('filename')
def filedelete():
    """Delete the file indicated by the query parameters. Returns 404
    if the original file does not exist. Any associated thumbnails will
    also be deleted.
    """
    image_db = get_image_db()
    storename = request.forms.filename

    basepath = path.join(settings.BASE_DIR, get_rel_path(request.forms.coll, thumb_p=False, storename=storename))
    thumbpath = path.join(settings.BASE_DIR, get_rel_path(request.forms.coll, thumb_p=True, storename=storename))
    pathname = path.join(basepath, storename)

    if s3_conn.S3_ENDPOINT:
        s3_conn.storage_delete(path.join(get_rel_path(request.forms.coll, False, storename), storename))
        pref = storename.split('.att')[0]
        resp = s3_conn.get_s3().list_objects_v2(Bucket=s3_conn.S3_BUCKET,
                                                      Prefix=s3_conn.s3_key(path.join(get_rel_path(request.forms.coll,
                                                      thumb_p=True, storename=storename), pref)))
        for obj in resp.get('Contents', []):
            s3_conn.get_s3().delete_object(Bucket=s3_conn.S3_BUCKET, Key=obj['Key'])
    else:
        if not path.exists(pathname):
            abort(404)
        log("Deleting %s" % pathname)
        remove(pathname)
        prefix = storename.split('.att')[0]
        base_filename = prefix[0:prefix.rfind('.')]
        pattern = path.join(thumbpath, base_filename + '*' + prefix[prefix.rfind('.') + 1:])
        log("Deleting thumbnails matching %s" % pattern)
        for name in glob(pattern):
            remove(name)

    response.content_type = 'text/plain; charset=utf-8'
    image_db.delete_image_record(storename)
    invalidate_cache()
    return 'Ok.'


def json_datetime_handler(x):
    if isinstance(x, datetime):
        return x.strftime(TIME_FORMAT)
    raise TypeError("Unknown type")


@app.route('/getImageRecord')
@require_token('file_string', always=True)
def get_image_record():
    image_db = get_image_db()
    query_params = request.query

    search_type = query_params.get('search_type', default='filename')
    query_string = query_params.get('file_string', default='')
    query_string = unquote(query_params.get('file_string', default=''))

    exact = str2bool(query_params.get('exact', default='False'))
    collection = query_params.get('coll')

    cache_columns = {
        'filename': 'original_filename',
        'path': 'original_path',
        'md5': 'orig_md5',
    }
    cache_col = cache_columns.get(search_type)
    if not cache_col:
        abort(400, 'Invalid search type')

    # md5 search is always exact
    cache_exact = exact if search_type != 'md5' else True
    record_list = cache_get_by_pattern(query_string, cache_col, cache_exact, collection)

    if record_list is None:
        search_functions = {
            'filename': lambda: image_db.get_image_record_by_original_filename(query_string, exact=exact,
                                                                               collection=collection),
            'path': lambda: image_db.get_image_record_by_original_path(query_string, exact=exact, collection=collection),
            'md5': lambda: image_db.get_image_record_by_original_image_md5(query_string, collection=collection)
        }
        try:
            with db_call_timeout(5):
                record_list = search_functions[search_type]()
        except DbCallTimeout:
            logging.error(f"DB_TIMEOUT getImageRecord search_type={search_type} query={query_string}")
            abort(503, "Database temporarily unavailable")
    log(f"Record list: {record_list}")

    if not record_list:
        log("Image not found, returning 404")
        abort(404)

    return json.dumps(record_list, indent=4, sort_keys=True, default=json_datetime_handler)


@app.route('/getexifdata')
@require_token('filename')
def get_exif_metadata():
    """Provides access to EXIF metadata."""
    storename = request.query.filename
    rel_path = get_rel_path(request.query.coll, thumb_p=False, storename=storename)
    basepath = path.join(settings.BASE_DIR, rel_path)
    pathname = path.join(basepath, storename)
    datatype = request.query.dt
    if s3_conn.S3_ENDPOINT:
        key = path.join(rel_path, storename)
        if not s3_conn.storage_exists(key):
            abort(404, f"Missing object: {key}")
        local_path = s3_conn.storage_download(key)
    else:
        local_path = pathname
        if not os.path.exists(local_path):
            abort(404, f"Missing file: {local_path}")

    exif_instance = MetadataTools(local_path)

    try:
        tags = exif_instance.read_exif_tags()
    except Exception as e:
        log(f"Error reading EXIF data: {e}")
        tags = {}

    if s3_conn.S3_ENDPOINT:
        s3_conn.remove_tempfile(local_path)

    if datatype == 'date':
        try:
            return str(tags['EXIF:DateTimeOriginal'])
        except KeyError:
            abort(404, 'DateTime not found in EXIF')

    response.content_type = 'application/json'
    return json.dumps(tags, indent=4, sort_keys=True, default=json_datetime_handler)


@app.route('/updateexifdata', method='POST')
@require_token('filename')
def updateexifdata():
    """Updates EXIF metadata"""
    storename = request.forms.filename
    exif_data = request.forms.exif_dict
    exif_data = json.loads(exif_data)
    base_root = path.join(get_rel_path(request.forms.coll, thumb_p=False, storename=storename))
    thumb_root = path.join(get_rel_path(request.forms.coll, thumb_p=True, storename=storename))
    orig_path = path.join(base_root, storename)
    thumb_path = path.join(thumb_root, storename)
    path_list = [orig_path, thumb_path]
    for rel_path in path_list:

        if not exif_data:
            abort(400)

        if s3_conn.S3_ENDPOINT:
            if not s3_conn.storage_exists(rel_path):
                abort(404, f"Missing object: {rel_path}")
            local_path = s3_conn.storage_download(rel_path)
        else:
            local_path = os.path.join(settings.BASE_DIR, rel_path)
            if not os.path.exists(local_path):
                abort(404, f"Missing file: {local_path}")

        if isinstance(exif_data, dict):
            md = MetadataTools(path=local_path)
            try:
                md.write_exif_tags(exif_dict=exif_data)
            except:
                response.content_type = 'text/plain; charset=utf-8'
                response.status = 422
                response.body = f"422 - metadata Tag not supported: {request.query.token}"
                log(response.body)
                return response
        else:
            log(f"exif_data is not a dictionary")

        if s3_conn.S3_ENDPOINT:
            try:
                with open(local_path, 'rb') as f:
                    s3_conn.storage_save(rel_path, f)
            finally:
                s3_conn.remove_tempfile(local_path)

        return f"{storename} updated with new exif metadata"


@app.route('/testkey')
@require_token('random', always=True)
def testkey():
    """If access to this resource succeeds, clients can conclude
    that they have a valid access key.
    """
    response.content_type = 'text/plain; charset=utf-8'
    return 'Ok.'


@app.route('/web_asset_store.xml')
@include_timestamp
def web_asset_store():
    """Serve an XML description of the URLs available here."""
    response.content_type = 'text/xml; charset=utf-8'
    return template('web_asset_store.xml', host="%s:%d" % (settings.SERVER_NAME, settings.SERVER_PORT),
                    protocol=settings.SERVER_PROTOCOL)


@app.route('/debug/health')
def debug_health():
    """Lightweight health check — does NOT touch S3 or MySQL."""
    try:
        import uwsgi
        worker_info = {
            'worker_id': uwsgi.worker_id(),
            'total_requests': uwsgi.total_requests(),
        }
    except (ImportError, AttributeError):
        worker_info = {}

    rusage = resource.getrusage(resource.RUSAGE_SELF)
    cache_info = {}
    try:
        cache_stat = os.stat(CACHE_DB_PATH)
        cache_info['size_mb'] = round(cache_stat.st_size / 1048576, 1)
        cache_info['age_s'] = round(time.time() - cache_stat.st_mtime, 1)
        cache_info['stale'] = os.path.exists(CACHE_INVALIDATE_PATH)
    except FileNotFoundError:
        cache_info['exists'] = False

    info = {
        'status': 'ok',
        'pid': os.getpid(),
        'tid': threading.get_ident(),
        'active_threads': threading.active_count(),
        'rss_kb': rusage.ru_maxrss,
        'utime_s': round(rusage.ru_utime, 2),
        'stime_s': round(rusage.ru_stime, 2),
        'worker': worker_info,
        'uptime_s': round(time.monotonic() - _server_start_time, 1),
        's3_temp_dirs': len(os.listdir('s3_temp')) if os.path.isdir('s3_temp') else 0,
        'image_cache': cache_info,
    }
    response.content_type = 'application/json'
    return json.dumps(info)


@app.route('/debug/pool')
def debug_pool():
    """MySQL connection pool stats."""
    from image_db import _pool_stats
    response.content_type = 'application/json'
    return json.dumps(_pool_stats)


@app.route('/')
def main_page():
    log("Hit root")
    return 'Specify attachment server'


if __name__ == '__main__':
    from bottle import run
    image_db = get_image_db()
    log("Starting up....")
    image_db = ImageDb()
    while image_db.connect() is not True:
        sleep(5)
        log("Retrying db connection....")
    image_db.create_tables()
    log("running server...")

    run(app=application,
        host='0.0.0.0',
        port=settings.PORT,
        server=settings.SERVER,
        debug=settings.DEBUG_APP,
        reloader=settings.DEBUG_APP
    )

    log("Exiting.")