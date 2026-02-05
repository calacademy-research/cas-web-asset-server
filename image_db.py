import mysql.connector
from mysql.connector import errorcode
from mysql.connector.pooling import MySQLConnectionPool
from retrying import retry
from contextlib import contextmanager

import settings
from datetime import datetime
import logging

TIME_FORMAT_NO_OFFSET = "%Y-%m-%d %H:%M:%S"
TIME_FORMAT = TIME_FORMAT_NO_OFFSET + "%z"

# Module-level connection pool (singleton)
_pool = None


def _get_pool():
    """Get or create the connection pool (singleton)."""
    global _pool
    if _pool is None:
        pool_config = {
            'pool_name': 'image_db_pool',
            'pool_size': 10,
            'pool_reset_session': True,
            'user': settings.SQL_USER,
            'password': settings.SQL_PASSWORD,
            'host': settings.SQL_HOST,
            'port': settings.SQL_PORT,
            'database': settings.SQL_DATABASE,
            'connect_timeout': 5,
        }
        _pool = MySQLConnectionPool(**pool_config)
        logging.info(f"Created MySQL connection pool with {pool_config['pool_size']} connections")
    return _pool


class ImageDb():
    def __init__(self):
        self._cnx = None

    def log(self, msg):
        if settings.DEBUG_APP:
            print(msg)

    @contextmanager
    def _get_connection(self):
        """Context manager for pooled connections."""
        cnx = _get_pool().get_connection()
        try:
            yield cnx
        finally:
            cnx.close()  # Returns connection to pool

    @contextmanager
    def get_connection(self):
        """Context manager for pooled connections with cursor."""
        cnx = _get_pool().get_connection()
        cursor = cnx.cursor(buffered=True)
        try:
            yield cnx, cursor
        finally:
            cursor.close()
            cnx.close()  # Returns to pool

    @retry(retry_on_exception=lambda e: isinstance(e, mysql.connector.OperationalError), stop_max_attempt_number=3,
           wait_exponential_multiplier=2)
    def get_cursor(self):
        """Get a cursor with a pooled connection. Caller must call release_cursor() after."""
        try:
            self._cnx = _get_pool().get_connection()
            self._cursor = self._cnx.cursor(buffered=True)
            return self._cursor
        except mysql.connector.OperationalError as e:
            logging.warning(f"Failed to get connection from pool: {e}")
            raise e

    def _release_connection(self):
        """Return connection to pool."""
        if self._cnx:
            try:
                self._cnx.close()  # Returns to pool
            except Exception:
                pass
            self._cnx = None
            self._cursor = None

    @property
    def cnx(self):
        """For backwards compatibility with code that accesses self.cnx directly."""
        return self._cnx

    def reset_connection(self):
        """Reset is now just releasing back to pool."""
        self.log(f"Releasing connection back to pool")
        self._release_connection()

    def connect(self):
        """No-op for backwards compatibility. Pool handles connections."""
        self.log("Using connection pool")
        return True

    def create_tables(self):
        TABLES = {}

        TABLES['images'] = (
            "CREATE TABLE if not exists `images`.`images` ("
            "   id int NOT NULL AUTO_INCREMENT primary key,"
            "  `original_filename` varchar(2000),"
            "  `url` varchar(500),"
            "  `universal_url` varchar(500),"
            "  `original_path` varchar(2000),"
            "  `redacted` BOOLEAN,"
            "  `internal_filename` varchar(500),"
            "  `notes` varchar(8192),"
            "  `datetime` datetime,"
            "  `collection` varchar(50)"
            ") ENGINE=InnoDB")

        cnx = _get_pool().get_connection()
        try:
            cursor = cnx.cursor(buffered=True)
            for table_name in TABLES:
                table_description = TABLES[table_name]
                try:
                    self.log(f"Creating table {table_name}...")
                    self.log(f"Sql: {TABLES[table_name]}")
                    cursor.execute(table_description)
                except mysql.connector.Error as err:
                    if err.errno == errorcode.ER_TABLE_EXISTS_ERROR:
                        self.log("already exists.")
                    else:
                        self.log(err.msg)
                else:
                    self.log("OK")
            cursor.close()
        finally:
            cnx.close()

        # Check and add orig_md5 column if needed
        cnx = _get_pool().get_connection()
        try:
            cursor = cnx.cursor(buffered=True)
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.columns WHERE table_name = 'images' AND column_name = 'orig_md5'")
            column_exists = cursor.fetchone()[0]

            if not column_exists:
                # Add the "orig_md5" column to the "images" table
                cursor.execute("ALTER TABLE images ADD COLUMN orig_md5 CHAR(32)")
            cursor.close()
        finally:
            cnx.close()

    def create_image_record(self,
                            original_filename,
                            url,
                            internal_filename,
                            collection,
                            original_path,
                            notes,
                            redacted,
                            datetime_record,
                            original_image_md5
                            ):
        cnx = _get_pool().get_connection()
        try:
            cursor = cnx.cursor(buffered=True)
            if original_filename is None:
                original_filename = "NULL"
            if original_image_md5 is None:
                original_image_md5 = "NULL"

            add_image = """INSERT INTO images
                            (original_filename, url, universal_url, internal_filename, collection, original_path,
                             notes, redacted, `datetime`, orig_md5)
                            VALUES (%s, %s, NULL, %s, %s, %s, %s, %s, %s, %s)"""

            # parameters
            params = (
                original_filename if original_filename is not None else None,
                url if url is not None else None,
                internal_filename if internal_filename is not None else None,
                collection if collection is not None else None,
                original_path if original_path is not None else None,
                notes if notes is not None else None,
                int(redacted),  # Ensure redacted is an integer
                datetime_record.strftime(TIME_FORMAT_NO_OFFSET) if datetime_record is not None else None,
                original_image_md5 if original_image_md5 is not None else None
            )

            self.log(f"Inserting image record. SQL: {add_image}")
            cursor.execute(add_image, params)
            cnx.commit()
            cursor.close()
        finally:
            cnx.close()

    @retry(retry_on_exception=lambda e: isinstance(e, Exception), stop_max_attempt_number=3)
    def update_redacted(self, internal_filename, is_redacted):
        sql = f"""
        update images set redacted = {is_redacted} where internal_filename = %s
        """
        logging.debug(f"update redacted: {sql}")
        cnx = _get_pool().get_connection()
        try:
            cursor = cnx.cursor(buffered=True)
            cursor.execute(sql, (internal_filename,))
            cnx.commit()
            cursor.close()
        finally:
            cnx.close()

    def get_record(self, where_clause):
        cnx = _get_pool().get_connection()
        try:
            cursor = cnx.cursor(buffered=True)
            query = f"""SELECT id, original_filename, url, universal_url, internal_filename, collection,original_path, notes, redacted, `datetime`, orig_md5
               FROM images
               {where_clause}"""

            cursor.execute(query)
            record_list = []
            for (
                    id, original_filename, url, universal_url, internal_filename, collection, original_path, notes,
                    redacted, datetime_record, orig_md5) in cursor:
                record_list.append({'id': id,
                                    'original_filename': original_filename,
                                    'url': url,
                                    'universal_url': universal_url,
                                    'internal_filename': internal_filename,
                                    'collection': collection,
                                    'original_path': original_path,
                                    'notes': notes,
                                    'redacted': redacted,
                                    'datetime': datetime.strptime(datetime_record, TIME_FORMAT),
                                    'orig_md5': orig_md5
                                    })
            cursor.close()
            return record_list
        finally:
            cnx.close()

    def get_image_record_by_internal_filename(self, internal_filename):
        cnx = _get_pool().get_connection()
        try:
            cursor = cnx.cursor(buffered=True)
            query = f"""SELECT id, original_filename, url, universal_url, internal_filename, collection,original_path, notes, redacted, `datetime`, orig_md5
               FROM images
               WHERE internal_filename = %s"""

            cursor.execute(query, (internal_filename,))

            record_list = []
            for (id,
                 original_filename,
                 url,
                 universal_url,
                 internal_filename,
                 collection,
                 original_path,
                 notes,
                 redacted,
                 datetime_record,
                 orig_md5) in cursor:
                record_list.append({'id': id,
                                    'original_filename': original_filename,
                                    'url': url,
                                    'universal_url': universal_url,
                                    'internal_filename': internal_filename,
                                    'collection': collection,
                                    'original_path': original_path,
                                    'notes': notes,
                                    'redacted': redacted,
                                    'datetime': datetime_record.strftime(TIME_FORMAT),
                                    'orig_md5': orig_md5
                                    })
            cursor.close()
            return record_list
        finally:
            cnx.close()  # Returns to pool

    def get_image_record_by_pattern(self, pattern, column, exact, collection):
        cnx = _get_pool().get_connection()
        try:
            cursor = cnx.cursor(buffered=True)
            if exact:
                query = f"""SELECT id, original_filename, url, universal_url, internal_filename, collection, original_path,
                                   notes, redacted, `datetime`, orig_md5
                            FROM images
                            WHERE {column} = %s"""
                params = [pattern]
            else:
                query = f"""SELECT id, original_filename, url, universal_url, internal_filename, collection, original_path,
                                   notes, redacted, `datetime`, orig_md5
                            FROM images
                            WHERE {column} LIKE %s"""
                params = [f"%{pattern}%"]

            if collection is not None:
                query += " AND collection = %s"
                params.append(collection)

            self.log(f"Executing query: {query} with params: {params}")

            cursor.execute(query, params)

            record_list = []
            for (id, original_filename, url, universal_url, internal_filename, collection, original_path, notes,
                 redacted, datetime_record, orig_md5) in cursor:
                record_list.append({'id': id,
                                    'original_filename': original_filename,
                                    'url': url,
                                    'universal_url': universal_url,
                                    'internal_filename': internal_filename,
                                    'collection': collection,
                                    'original_path': original_path,
                                    'notes': notes,
                                    'redacted': redacted,
                                    'datetime': datetime_record,
                                    'orig_md5': orig_md5
                                    })
                self.log(f"Found at least one record: {record_list[-1]}")
            cursor.close()
            return record_list
        finally:
            cnx.close()

    def get_image_record_by_original_path(self, original_path, exact, collection):
        record_list = self.get_image_record_by_pattern(original_path, 'original_path', exact, collection)
        return record_list

    def get_image_record_by_original_filename(self, original_filename, exact, collection):
        record_list = self.get_image_record_by_pattern(original_filename, 'original_filename', exact, collection)
        return record_list

    def get_image_record_by_original_image_md5(self, md5, collection):
        record_list = self.get_image_record_by_pattern(md5, 'orig_md5', True, collection)
        return record_list

    def delete_image_record(self, internal_filename):
        cnx = _get_pool().get_connection()
        try:
            cursor = cnx.cursor(buffered=True)
            delete_image = (f"""delete from images where internal_filename= %s """)

            self.log(f"deleting image record. SQL: {delete_image}")
            cursor.execute(delete_image, (internal_filename,))
            cnx.commit()
            cursor.close()
        finally:
            cnx.close()

    def execute(self, sql):
        cnx = _get_pool().get_connection()
        try:
            cursor = cnx.cursor(buffered=True)
            logging.debug(f"SQL: {sql}")
            cursor.execute(sql)
            cnx.commit()
            cursor.close()
        finally:
            cnx.close()

    def get_collection_list(self):
        cnx = _get_pool().get_connection()
        try:
            cursor = cnx.cursor(buffered=True)
            query = f"""select collection from collection"""

            cursor.execute(query)
            collection_list = []
            for (collection) in cursor:
                collection_list.append(collection)
            cursor.close()
            return collection_list
        finally:
            cnx.close()
    #
    #  not used 4/10/23 - left for referenece for now
    #

    # def search(self, filename, match_exact_data):
    #     params = {
    #         'filename': filename,
    #         'exact': match_exact_data,
    #         'token': self.generate_token(self.get_timestamp(), filename)
    #     }
    #
    #     r = requests.get(self.build_url("getImageRecordByOrigFilename"), params=params)
    #     print(f"Search result: {r.status_code}")
    #     if (r.status_code == 404):
    #         print(f"No records found for {arg}")
    #         return False
    #     if r.status_code != 200:
    #         print(f"Unexpected search result: {r.status_code}; aborting.")
    #         return
    #     data = json.loads(r.text)
    #     print(
    #         f"collection, datetime, id, internal_filename, notes, original filename, original path, redacted, universal URL, URL")
    #     if len(data) == 0:
    #         print("No match.")
    #     else:
    #         for item in data:
    #             print(
    #                 f"{item['collection']},{item['datetime']},{item['internal_filename']},{item['notes']},{item['original_filename']},{item['original_path']},{item['redacted']},{item['universal_url']},{item['url']}")