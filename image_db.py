import mysql.connector
from mysql.connector import errorcode, pooling
from retrying import retry

import settings
from datetime import datetime
import logging
import configparser

TIME_FORMAT_NO_OFFSET = "%Y-%m-%d %H:%M:%S"
TIME_FORMAT = TIME_FORMAT_NO_OFFSET + "%z"

class ImageDb:
    def __init__(self):
        self.pool_size = self.init_pool_size()
        self.connection_pool = None

    def init_pool_size(self):
        """sets pool size by getting # of workers and threads from uwsgi"""
        config = configparser.ConfigParser()
        config.read("./uwsgi.ini")
        workers = int(config.get("uwsgi", "workers", fallback=4))  # Default to 1 worker
        threads = int(config.get("uwsgi", "threads", fallback=8))  # Default to 1 thread
        return workers * threads


    def log(self, msg):
        if settings.DEBUG_APP:
            print(msg)

    def initialize_pool(self):
        """
        Initialize the connection pool lazily if it hasn't been created yet.
        """
        if not self.connection_pool:
            self.log("Initializing connection pool...")
            try:
                self.connection_pool = mysql.connector.pooling.MySQLConnectionPool(
                    pool_name="image_db_pool",
                    pool_size= self.pool_size,  # Adjust pool size as needed
                    user=settings.SQL_USER,
                    password=settings.SQL_PASSWORD,
                    host=settings.SQL_HOST,
                    port=settings.SQL_PORT,
                    database=settings.SQL_DATABASE,
                )
                self.log("Connection pool initialized.")
            except mysql.connector.Error as err:
                self.log(f"Failed to initialize connection pool: {err}")
                raise

    @retry(retry_on_exception=lambda e: isinstance(e, mysql.connector.Error), stop_max_attempt_number=3, wait_exponential_multiplier=1000)
    def get_cursor(self):
        """
        Get a connection from the pool and create a cursor.
        """
        try:
            self.initialize_pool()  # Ensure the pool is initialized
            connection = self.connection_pool.get_connection()
            return connection.cursor(buffered=True), connection
        except mysql.connector.Error as e:
            self.log(f"Error getting cursor: {e}")
            raise

    def close_connection(self, connection):
        """
        Return a connection to the pool.
        """
        if connection:
            try:
                connection.close()
                self.log("Connection returned to the pool.")
            except mysql.connector.Error as e:
                self.log(f"Error closing connection: {e}")

    def create_tables(self):
        """
        Create the required database tables if they do not exist.
        """
        TABLES = {
            'images': (
                "CREATE TABLE IF NOT EXISTS `images` ("
                "  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,"
                "  original_filename VARCHAR(2000),"
                "  url VARCHAR(500),"
                "  universal_url VARCHAR(500),"
                "  original_path VARCHAR(2000),"
                "  redacted BOOLEAN,"
                "  internal_filename VARCHAR(500),"
                "  notes VARCHAR(8192),"
                "  datetime DATETIME,"
                "  collection VARCHAR(50),"
                "  orig_md5 CHAR(32)"
                ") ENGINE=InnoDB"
            )
        }

        cursor, connection = None, None
        try:
            cursor, connection = self.get_cursor()
            for table_name, table_description in TABLES.items():
                try:
                    self.log(f"Creating table {table_name}...")
                    cursor.execute(table_description)
                    self.log(f"Table {table_name} creation: OK")
                except mysql.connector.Error as err:
                    if err.errno == errorcode.ER_TABLE_EXISTS_ERROR:
                        self.log(f"Table {table_name} already exists.")
                    else:
                        self.log(f"Error creating table {table_name}: {err}")
        finally:
            if cursor:
                cursor.close()
            if connection:
                self.close_connection(connection)

    def create_image_record(self, original_filename, url, internal_filename, collection, original_path, notes, redacted, datetime_record, original_image_md5):
        cursor, connection = None, None
        try:
            cursor, connection = self.get_cursor()

            # Build the INSERT SQL query
            add_image = (f"""INSERT INTO images
                            (original_filename, url, universal_url, internal_filename, collection, original_path, notes, redacted, datetime, orig_md5)
                            VALUES (
                            "{original_filename or 'NULL'}",
                            "{url}",
                            NULL,
                            "{internal_filename}",
                            "{collection}",
                            "{original_path}",
                            "{notes}",
                            "{int(redacted)}",
                            "{datetime_record.strftime(TIME_FORMAT_NO_OFFSET)}",
                            "{original_image_md5 or 'NULL'}")""")

            self.log(f"Inserting image record. SQL: {add_image}")
            cursor.execute(add_image)
            connection.commit()
        except mysql.connector.Error as e:
            self.log(f"Error inserting image record: {e}")
            raise
        finally:
            if cursor:
                cursor.close()
            if connection:
                self.close_connection(connection)

    @retry(retry_on_exception=lambda e: isinstance(e, Exception), stop_max_attempt_number=3)
    def update_redacted(self, internal_filename, is_redacted):
        cursor, connection = None, None
        try:
            sql = f"""
            UPDATE images SET redacted = {is_redacted} WHERE internal_filename = '{internal_filename}'
            """
            logging.debug(f"update redacted: {sql}")
            cursor, connection = self.get_cursor()
            cursor.execute(sql)
            connection.commit()
        except mysql.connector.Error as e:
            self.log(f"Error updating redacted: {e}")
            raise
        finally:
            if cursor:
                cursor.close()
            if connection:
                self.close_connection(connection)

    def get_record(self, where_clause):
        cursor, connection = None, None
        try:
            query = f"""SELECT id, original_filename, url, universal_url, internal_filename, collection, original_path, notes, redacted, datetime, orig_md5
                FROM images 
                {where_clause}"""

            cursor, connection = self.get_cursor()
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

            return record_list
        except mysql.connector.Error as e:
            self.log(f"Error fetching records: {e}")
            raise
        finally:
            if cursor:
                cursor.close()
            if connection:
                self.close_connection(connection)

    def get_image_record_by_internal_filename(self, internal_filename):
        cursor, connection = None, None
        try:
            query = f"""SELECT id, original_filename, url, universal_url, internal_filename, collection, original_path, notes, redacted, datetime, orig_md5
               FROM images 
               WHERE internal_filename = '{internal_filename}'"""

            cursor, connection = self.get_cursor()
            cursor.execute(query)
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

            return record_list
        except mysql.connector.Error as e:
            self.log(f"Error fetching record by internal filename: {e}")
            raise
        finally:
            if cursor:
                cursor.close()
            if connection:
                self.close_connection(connection)

    def get_image_record_by_pattern(self, pattern, column, exact, collection):
        cursor, connection = None, None
        try:
            if exact:
                query = f"""SELECT id, original_filename, url, universal_url, internal_filename, collection, original_path, notes, redacted, datetime, orig_md5
                FROM images 
                WHERE {column} = '{pattern}'"""
            else:
                query = f"""SELECT id, original_filename, url, universal_url, internal_filename, collection, original_path, notes, redacted, datetime, orig_md5
                FROM images 
                WHERE {column} LIKE '{pattern}'"""
            if collection is not None:
                query += f""" AND collection = '{collection}'"""
            self.log(f"Query get_image_record_by_{column}: {query}")

            cursor, connection = self.get_cursor()
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
                                    'datetime': datetime_record,
                                    'orig_md5': orig_md5
                                    })
                self.log(f"Found at least one record: {record_list[-1]}")

            return record_list
        except mysql.connector.Error as e:
            self.log(f"Error fetching records by pattern: {e}")
            raise
        finally:
            if cursor:
                cursor.close()
            if connection:
                self.close_connection(connection)

    def get_image_record_by_original_path(self, original_path, exact, collection):
        return self.get_image_record_by_pattern(original_path, 'original_path', exact, collection)


    def get_image_record_by_original_filename(self, original_filename, exact, collection):
        return self.get_image_record_by_pattern(original_filename, 'original_filename', exact, collection)


    def get_image_record_by_original_image_md5(self, md5, collection):
        return self.get_image_record_by_pattern(md5, 'orig_md5', True, collection)

    def delete_image_record(self, internal_filename):
        cursor, connection = None, None
        try:
            delete_image = f"""DELETE FROM images WHERE internal_filename='{internal_filename}'"""
            self.log(f"Deleting image record. SQL: {delete_image}")

            cursor, connection = self.get_cursor()
            cursor.execute(delete_image)
            connection.commit()
        except mysql.connector.Error as e:
            self.log(f"Error deleting image record: {e}")
            raise
        finally:
            if cursor:
                cursor.close()
            if connection:
                self.close_connection(connection)

    def execute(self, sql):
        cursor, connection = None, None
        try:
            cursor, connection = self.get_cursor()
            logging.debug(f"SQL: {sql}")
            cursor.execute(sql)
            connection.commit()
        except mysql.connector.Error as e:
            self.log(f"Error executing query: {e}")
            raise
        finally:
            if cursor:
                cursor.close()
            if connection:
                self.close_connection(connection)

    def get_collection_list(self):
        cursor, connection = None, None
        try:
            query = f"""SELECT collection FROM collection"""
            cursor, connection = self.get_cursor()
            cursor.execute(query)
            collection_list = [collection[0] for collection in cursor.fetchall()]
            return collection_list
        except mysql.connector.Error as e:
            self.log(f"Error fetching collection list: {e}")
            raise
        finally:
            if cursor:
                cursor.close()
            if connection:
                self.close_connection(connection)

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
