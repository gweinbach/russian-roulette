import os
import unittest

from discord.key_value import FileStorageKeyIntValue, InMemoryKeyIntValue


class TestKeyValue(unittest.TestCase):

    TEST_DB="test.db"

    def _deleteTestDb(self):
        if os.path.exists(self.TEST_DB):
            os.remove(self.TEST_DB)

    def setUp(self) -> None:
        self._deleteTestDb()

    def tearDown(self) -> None:
        self._deleteTestDb()


    def test_file_storage_key_int_value(self):

        # Given a File Storage
        kv = FileStorageKeyIntValue(self.TEST_DB)

        # When I put an int in it
        kv.put_int("a", 1)

        # Then I can read it
        self.assertEqual(kv.get_int("a"), 1)

        # And increment it
        kv.increment_int("a", 5)
        self.assertEqual(kv.get_int("a"), 6)

        # And decrement it
        kv.decrement_int("a", 10)
        self.assertEqual(kv.get_int("a"), -4)

        # When I look for a non existing value
        # Then I get the default value : 0
        self.assertEqual(kv.get_int("b"), 0)

        # The read value is stored
        self.assertEqual(kv.get_int("b", 3), 0)

        # Then I can read a non existing value provided I give a default value
        self.assertEqual(kv.get_int("c", 3), 3)


        # When I close de DB
        del(kv)

        # When I reopen it
        kv2 = FileStorageKeyIntValue(self.TEST_DB)

        # Then data values are still there
        self.assertEqual(kv2.get_int("a"), -4)
        self.assertEqual(kv2.get_int("b", 5), 0)
        self.assertEqual(kv2.get_int("c"), 3)
        self.assertEqual(kv2.get_int("d", 5), 5)



    def test_in_memory_key_int_value(self):

        # Given a File Storage
        kv = InMemoryKeyIntValue()

        # When I put an int in it
        kv.put_int("a", 1)

        # Then I can read it
        self.assertEqual(kv.get_int("a"), 1)

        # And increment it
        kv.increment_int("a", 5)
        self.assertEqual(kv.get_int("a"), 6)

        # And decrement it
        kv.decrement_int("a", 10)
        self.assertEqual(kv.get_int("a"), -4)

        # When I look for a non existing value
        # Then I get the default value : 0
        self.assertEqual(kv.get_int("b"), 0)

        # The read value is stored
        self.assertEqual(kv.get_int("b", 3), 0)

        # Then I can read a non existing value provided I give a default value
        self.assertEqual(kv.get_int("c", 3), 3)



if __name__ == '__main__':
    unittest.main()
