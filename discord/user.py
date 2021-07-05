
class User:

    def __init__(self,
                 id: str,
                 name: str):
        self.id = id
        self.name = name

    def mention(self):
        return str(self.name)
