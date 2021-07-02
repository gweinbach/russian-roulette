from .user import User


class Message:

    def __init__(self, id: int, author: User):
        self.id = id
        self.author = author
        print(self)

    @classmethod
    def respond(self, response: str):
        pass
