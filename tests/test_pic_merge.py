import unittest
import shutil
import os
import picturae_csv_create as pcc
from datetime import date, timedelta
from tests.testing_tools import TestingTools

def test_date():
    """test_date: creates an arbitrary date, 20 years in the past from today's date,
       to create test files for, so as not to overwrite current work
       ! if this code outlives 20 years of use I would be impressed"""
    unit_date = date.today() - timedelta(days=365 * 20)
    return str(unit_date)


class CsvReadMergeTests(unittest.TestCase, TestingTools):
    """this class contains methods which test outputs of the
       csv_read_folder function , and csv_merge functions from
       picturae_import.py"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.date_string = self.test_date()

    # will think of ways to shorten this setup function
    def setUp(self):
        """creates fake datasets with dummy columns,
          that have a small subset of representive real column names,
          so that test merges and uploads can be performed.
          """
        # print("setup called!")
        self.CsvCreatePicturae = pcc.CsvCreatePicturae(date_string=self.date_string, istesting=True)
        # maybe create a separate function for setting up test directories
        path_type_list = ['folder', 'specimen']
        path_list = []
        for path_type in path_type_list:
            path = 'picturae_csv/' + str(self.date_string) + '/picturae_' + str(path_type) + '(' + \
                    str(self.date_string) + ').csv'

            path_list.append(path)

            os.makedirs(os.path.dirname(path), exist_ok=True)

            open(path, 'a').close()

        # writing csvs
        self.create_fake_dataset(path_list=path_list, num_records=50)


    def test_file_empty(self):
        """tests if dataset returns as empty set or not"""
        self.assertEqual(self.CsvCreatePicturae.csv_read_folder('folder').empty, False)
        self.assertEqual(self.CsvCreatePicturae.csv_read_folder('specimen').empty, False)

    def test_file_colnumber(self):
        """tests if expected # of columns given test datasets"""
        self.assertEqual(len(self.CsvCreatePicturae.csv_read_folder('folder').columns), 3)
        self.assertEqual(len(self.CsvCreatePicturae.csv_read_folder('specimen').columns), 3)

    def test_barcode_column_present(self):
        """tests if barcode column is present
           (test if column names loaded correctly,
           specimen_barcode being in required in both csvs)"""
        self.assertEqual('specimen_barcode' in self.CsvCreatePicturae.csv_read_folder('folder').columns, True)
        self.assertEqual('specimen_barcode' in self.CsvCreatePicturae.csv_read_folder('specimen').columns, True)

    # these tests are for the csv merge function
    def test_merge_num_columns(self):
        """test merge with sample data set , checks if shared columns are removed,
           and that the merge occurs with expected # of columns"""
        # -3 as merge function drops duplicate columns automatically
        self.CsvCreatePicturae.csv_merge()
        self.assertEqual(len(self.CsvCreatePicturae.record_full.columns),
                         len(self.CsvCreatePicturae.csv_read_folder('folder').columns) +
                         len(self.CsvCreatePicturae.csv_read_folder('specimen').columns) - 3)

    def test_index_length_matches(self):
        """checks whether dataframe, length changes,
           which would hint at barcode mismatch problem,
           folder and specimen csvs should
           always be a 100% match on barcodes
           """
        self.CsvCreatePicturae.csv_merge()
        csv_folder = self.CsvCreatePicturae.csv_read_folder('folder')
        # test merge index before and after
        self.assertEqual(len(self.CsvCreatePicturae.record_full),
                         len(csv_folder))

    def test_unequalbarcode_raise(self):
        """checks whether inserted errors in barcode column raise
           a Value error raise in the merge function"""
        # testing output
        csv_folder = self.CsvCreatePicturae.csv_read_folder(folder_string="folder")
        csv_specimen = self.CsvCreatePicturae.csv_read_folder(folder_string="specimen")
        self.assertEqual(set(csv_folder['specimen_barcode']), set(csv_specimen['specimen_barcode']))

    def test_output_isnot_empty(self):
        """tests whether merge function accidentally
           produces an empty dataframe"""
        self.CsvCreatePicturae.csv_merge()
        # testing output
        self.assertFalse(self.CsvCreatePicturae.record_full.empty)

    def tearDown(self):
        """deletes destination directories for dummy datasets"""
        # print("teardown called!")
        # deleting instance
        del self.CsvCreatePicturae
        # deleting folders
        date_string = test_date()

        folder_path = 'picturae_csv/' + str(date_string) + '/picturae_folder(' + \
                      str(date_string) + ').csv'

        shutil.rmtree(os.path.dirname(folder_path))
