
class User:

    def __init__(self, id: int):
        self.id = id

    @classmethod
    def mention(self):
        return str(self.id)
