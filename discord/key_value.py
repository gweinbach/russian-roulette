from dbm import gnu


class KeyStringValue:
    """
    Abstract key value storage for string values
    """

    def put(self, key: str, value: str) -> None:
        pass

    def get(self, key: str, default: str = "") -> str:
        return default


class KeyIntValue:
    """
    Abstract key value storage for int values
    """

    def put_int(self, key: str, int_value: int) -> None:
        """
        Abstract method
        :param key:
        :param int_value:
        :return:
        """
        pass

    def get_int(self, key, default: int = 0):
        """
        Abstract method
        :param key:
        :param default:
        :return:
        """
        return default

    def increment_int(self, key: str, int_value: int) -> None:
        self.put_int(key, self.get_int(key, 0) + int_value)

    def decrement_int(self, key: str, int_value: int) -> None:
        self.put_int(key, self.get_int(key, 0) - int_value)


class InMemoryKeyStringValue(KeyStringValue):
    """
    A simple in memory KeyStringValue implementation backed by a dictionary
    """

    def __init__(self):
        self.dict = {}

    def put(self, key: str, value: str) -> None:
        self.dict[key] = value

    def get(self, key: str, default: str = "") -> str:
        existing = self.dict.get(key)
        if existing is None:
            self.put(key, default)
            return default
        else:
            return existing


class InMemoryKeyIntValue(KeyIntValue):
    """
    A simple in memory KeyIntValue implementation backed by a dictionary
    """

    def __init__(self):
        self.dict = {}

    def put_int(self, key: str, int_value: int) -> None:
        self.dict[key] = int_value

    def get_int(self, key: str, default: int = 0) -> int:
        existing = self.dict.get(key)
        if existing is None:
            self.put_int(key, default)
            return default
        else:
            return existing


class FileStorageKeyStringValue(KeyStringValue):

    def __init__(self, storage_file_name: str = "key-value.db"):
        self.storage = gnu.open(storage_file_name, 'cs')

    def put(self, key: str, value: str) -> None:
        self.storage[key] = value

    def get(self, key: str, default: str = "") -> str:
        existing = self.storage.get(key)
        if existing is None:
            self.put(key, default)
            return default
        else:
            return existing

    def __del__(self) -> None:
        self.storage.close()


class FileStorageKeyIntValue(FileStorageKeyStringValue, KeyIntValue):

    def __init__(self, storage_file_name: str = "key-value.db"):
          super().__init__(storage_file_name)

    def put_int(self, key: str, int_value: int) -> None:
        self.put(key, str(int_value))

    def get_int(self, key, default: int = 0):
        return int(self.get(key, str(default)))

