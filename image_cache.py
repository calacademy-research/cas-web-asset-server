"""SQLite-based read cache for the images table.

Eliminates MySQL from the hot read path.  The cache is a SQLite file
at /tmp/image_cache.db, rebuilt from MySQL periodically.  All 32 uWSGI
workers share the same physical pages via OS page cache — near-zero
per-worker memory overhead.

Rebuild triggers:
  - First request when the file doesn't exist
  - A marker file signals invalidation after writes
  - Periodic check every 60 s

Every public function returns None on failure, signalling the caller
to fall back to MySQL.
"""

import fcntl
import logging
import os
import sqlite3
import time
import threading

from image_db import _get_pool, TIME_FORMAT_NO_OFFSET

CACHE_DB_PATH = '/tmp/image_cache.db'
CACHE_LOCK_PATH = '/tmp/image_cache.lock'
CACHE_INVALIDATE_PATH = '/tmp/image_cache.invalidate'

_check_lock = threading.Lock()
_last_check_monotonic = 0.0
_CHECK_INTERVAL_S = 10     # how often workers stat() the marker file
_DEBOUNCE_S = 30           # wait for writes to quiesce before rebuilding


# ── build / rebuild ────────────────────────────────────────────────

def _build_cache_db():
    """Full rebuild: MySQL → SQLite temp file → atomic rename."""
    t0 = time.monotonic()
    tmp_path = CACHE_DB_PATH + '.tmp.' + str(os.getpid())

    conn = sqlite3.connect(tmp_path)
    conn.execute('PRAGMA journal_mode=OFF')
    conn.execute('PRAGMA synchronous=OFF')
    conn.execute('PRAGMA cache_size=-65536')  # 64 MB page cache during build
    conn.execute('''CREATE TABLE images (
        id          INTEGER PRIMARY KEY,
        original_filename  TEXT,
        url                TEXT,
        universal_url      TEXT,
        internal_filename  TEXT,
        collection         TEXT,
        original_path      TEXT,
        notes              TEXT,
        redacted           INTEGER,
        datetime           TEXT,
        orig_md5           TEXT
    )''')

    # Stream rows from MySQL in server-side cursor fashion
    pool = _get_pool()
    cnx = pool.get_connection()
    row_count = 0
    try:
        cursor = cnx.cursor(buffered=False)  # unbuffered — stream rows
        cursor.execute(
            "SELECT id, original_filename, url, universal_url, "
            "internal_filename, collection, original_path, notes, "
            "redacted, `datetime`, orig_md5 FROM images"
        )
        batch = []
        for row in cursor:
            dt = row[9]
            if dt is not None and not isinstance(dt, str):
                dt = dt.strftime(TIME_FORMAT_NO_OFFSET)
            batch.append((
                row[0], row[1], row[2], row[3], row[4],
                row[5], row[6], row[7], row[8], dt, row[10]
            ))
            if len(batch) >= 50000:
                conn.executemany(
                    'INSERT INTO images VALUES (?,?,?,?,?,?,?,?,?,?,?)', batch
                )
                row_count += len(batch)
                batch = []
        if batch:
            conn.executemany(
                'INSERT INTO images VALUES (?,?,?,?,?,?,?,?,?,?,?)', batch
            )
            row_count += len(batch)
        cursor.close()
    finally:
        cnx.close()

    conn.execute(
        'CREATE INDEX idx_cache_internal_filename ON images(internal_filename)'
    )
    conn.execute(
        'CREATE INDEX idx_cache_original_filename ON images(original_filename)'
    )
    conn.execute(
        'CREATE INDEX idx_cache_original_path ON images(original_path)'
    )
    conn.execute(
        'CREATE INDEX idx_cache_orig_md5 ON images(orig_md5)'
    )
    conn.execute(
        'CREATE INDEX idx_cache_collection ON images(collection)'
    )
    conn.commit()
    conn.close()

    os.replace(tmp_path, CACHE_DB_PATH)
    # Clear invalidation marker
    try:
        os.unlink(CACHE_INVALIDATE_PATH)
    except FileNotFoundError:
        pass

    elapsed = round((time.monotonic() - t0) * 1000)
    logging.info(f"IMAGE_CACHE rebuilt: {row_count} rows in {elapsed}ms")


def rebuild_cache():
    """Rebuild with file-level locking so only one worker builds at a time."""
    lock_fd = None
    try:
        lock_fd = open(CACHE_LOCK_PATH, 'w')
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # Another process is already building — wait for it to finish
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            return  # The other process wrote the file; we're done
        _build_cache_db()
    except Exception as e:
        logging.error(f"IMAGE_CACHE rebuild failed: {e}")
    finally:
        if lock_fd:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()
            except Exception:
                pass


def invalidate_cache():
    """Mark cache as stale.  Called after any write to MySQL."""
    try:
        with open(CACHE_INVALIDATE_PATH, 'w') as f:
            f.write(str(time.time()))
    except Exception:
        pass


# ── internal helpers ───────────────────────────────────────────────

def _needs_rebuild():
    if not os.path.exists(CACHE_DB_PATH):
        return True
    try:
        marker_mtime = os.stat(CACHE_INVALIDATE_PATH).st_mtime
    except FileNotFoundError:
        return False
    # Debounce: don't rebuild while writes are still arriving.
    # Only rebuild once the marker is older than _DEBOUNCE_S,
    # meaning writes have quiesced.
    age = time.time() - marker_mtime
    if age < _DEBOUNCE_S:
        return False  # too fresh — writes still in progress
    return True


def _ensure_cache():
    """Lightweight gate — at most one stat() per _CHECK_INTERVAL_S.

    NEVER blocks on a rebuild during a request.  If the cache doesn't
    exist or is stale, kicks off an async rebuild and returns False so
    the caller falls back to MySQL.
    """
    global _last_check_monotonic
    now = time.monotonic()
    if now - _last_check_monotonic < _CHECK_INTERVAL_S:
        if os.path.exists(CACHE_DB_PATH):
            return True
    with _check_lock:
        # Double-check after acquiring lock
        if now - _last_check_monotonic < _CHECK_INTERVAL_S:
            if os.path.exists(CACHE_DB_PATH):
                return True
        _last_check_monotonic = now
        if _needs_rebuild():
            # Kick off async rebuild — don't block the request
            t = threading.Thread(target=rebuild_cache, daemon=True)
            t.start()
            return os.path.exists(CACHE_DB_PATH)
    return os.path.exists(CACHE_DB_PATH)


def _get_conn():
    """Read-only connection to the cache file."""
    return sqlite3.connect(
        f'file:{CACHE_DB_PATH}?mode=ro&immutable=1',
        uri=True,
        timeout=1,
    )


def _rows_to_dicts(cursor):
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


# ── public read API ────────────────────────────────────────────────

def cache_get_by_internal_filename(internal_filename):
    """Equivalent to ImageDb.get_image_record_by_internal_filename.
    Returns list of dicts, or None on any failure (caller falls back to MySQL).
    """
    try:
        if not _ensure_cache():
            return None
        conn = _get_conn()
        try:
            cur = conn.execute(
                'SELECT * FROM images WHERE internal_filename = ?',
                (internal_filename,),
            )
            return _rows_to_dicts(cur)
        finally:
            conn.close()
    except Exception as e:
        logging.warning(f"IMAGE_CACHE miss internal_filename={internal_filename}: {e}")
        return None


def cache_warm():
    """Pre-build the cache (call before starting workers).

    Usage from container:
        python -c 'from image_cache import cache_warm; cache_warm()'
    """
    logging.basicConfig(level=logging.INFO)
    rebuild_cache()


def cache_get_by_pattern(pattern, column, exact, collection):
    """Equivalent to ImageDb.get_image_record_by_pattern.
    Handles both exact and LIKE queries.
    Returns list of dicts, or None on any failure.
    """
    allowed = {'original_filename', 'original_path', 'orig_md5'}
    if column not in allowed:
        return None

    try:
        if not _ensure_cache():
            return None
        conn = _get_conn()
        try:
            if exact:
                sql = f'SELECT * FROM images WHERE {column} = ?'
                params = [pattern]
            else:
                sql = f'SELECT * FROM images WHERE {column} LIKE ?'
                params = [f'%{pattern}%']

            if collection is not None:
                sql += ' AND collection = ?'
                params.append(collection)

            cur = conn.execute(sql, params)
            return _rows_to_dicts(cur)
        finally:
            conn.close()
    except Exception as e:
        logging.warning(f"IMAGE_CACHE miss {column}={pattern}: {e}")
        return None
