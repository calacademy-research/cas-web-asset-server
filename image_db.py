import mysql.connector
from mysql.connector import errorcode
from retrying import retry

import settings
from datetime import datetime
import logging

TIME_FORMAT_NO_OFFSET = "%Y-%m-%d %H:%M:%S"
TIME_FORMAT = TIME_FORMAT_NO_OFFSET + "%z"


class ImageDb():
    def __init__(self):
        self.cnx = None

    def log(self, msg):
        if settings.DEBUG_APP:
            print(msg)

    def retry_if_operational_error(exception):
        pass


    @retry(retry_on_exception=lambda e: isinstance(e, mysql.connector.OperationalError), stop_max_attempt_number=3,
           wait_exponential_multiplier=2)
    def get_cursor(self):
        try:
            if self.cnx is None:
                self.connect()
            return self.cnx.cursor(buffered=True)
        except mysql.connector.OperationalError as e:
            logging.warning("Failed to connect, resetting DB connection and sleeping")
            self.reset_connection()
            raise e

    def reset_connection(self):
        self.log(f"Resetting connection to {settings.SQL_HOST}")

        if self.cnx:
            try:
                self.cnx.close()
            except Exception:
                pass
        self.connect()

    def connect(self):

        try:
            self.cnx = mysql.connector.connect(user=settings.SQL_USER,
                                               password=settings.SQL_PASSWORD,
                                               host=settings.SQL_HOST,
                                               port=settings.SQL_PORT,
                                               database=settings.SQL_DATABASE)

        except mysql.connector.Error as err:
            if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
                self.log(
                    f"SQL: Access denied to image server database. host: {settings.SQL_HOST} user: {settings.SQL_USER}")
            elif err.errno == errorcode.ER_BAD_DB_ERROR:
                self.log("Database does not exist")
            else:
                self.log(err)
            return False
        except Exception as ex:
            self.log(f"Unknown error:{ex}")
            return False
        self.log("Db connected")

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

        cursor = self.get_cursor()

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
        cursor = self.get_cursor()

        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.columns WHERE table_name = 'images' AND column_name = 'orig_md5'")
        column_exists = cursor.fetchone()[0]

        if not column_exists:
            # Add the "orig_md5" column to the "images" table
            cursor.execute("ALTER TABLE images ADD COLUMN orig_md5 CHAR(32)")

        cursor.close()

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

        cursor = self.get_cursor()
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

        self.log(f"Inserting imageInserting image record. SQL: {add_image}")
        cursor.execute(add_image, params)
        self.cnx.commit()
        cursor.close()

    @retry(retry_on_exception=lambda e: isinstance(e, Exception), stop_max_attempt_number=3)
    def update_redacted(self, internal_filename, is_redacted):
        sql = f"""
        update images set redacted = {is_redacted} where internal_filename = %s 
        """

        logging.debug(f"update redacted: {sql}")
        cursor = self.get_cursor()
        cursor.execute(sql, (internal_filename,))
        self.cnx.commit()
        cursor.close()

    def get_record(self, where_clause):

        cursor = self.get_cursor()

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

    def get_image_record_by_internal_filename(self, internal_filename):
        cursor = self.get_cursor()

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

    def get_image_record_by_pattern(self, pattern, column, exact, collection):
        cursor = self.get_cursor()
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
        cursor = self.get_cursor()

        delete_image = (f"""delete from images where internal_filename= %s """)

        self.log(f"deleting image record. SQL: {delete_image}")
        cursor.execute(delete_image, (internal_filename,))
        self.cnx.commit()
        cursor.close()

    def execute(self, sql):
        cursor = self.get_cursor()
        logging.debug(f"SQL: {sql}")
        cursor.execute(sql)
        self.cnx.commit()
        cursor.close()

    def get_collection_list(self):
        cursor = self.get_cursor()

        query = f"""select collection from collection"""

        cursor.execute(query)
        collection_list = []
        for (collection) in cursor:
            collection_list.append(collection)
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