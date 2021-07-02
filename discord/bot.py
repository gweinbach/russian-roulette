
from .message import Message


class IntDictionary:

    def __init__(self):
        pass

    def increment_int(self, key, int_value: int):
        pass

    def decrement_int(self, key, int_value: int):
        pass

    def get_int(self, key, default=0):
        return 0


class Bot:
    def __init__(self, token: str):
        self.token = token
        self.kv = IntDictionary()
        print("Created a bot:", self)

    @staticmethod
    def run_forever():
        print("Running bot loop")

    @staticmethod
    def register_command(command_name, cooldown=0):
        print(f"Registered command: {command_name} that cools down in {cooldown}")

        def decorator(function):
            def wrapper(bot: Bot, message: Message):
                print("Bot {bot} is receiving message {message} related to command {command_name}")
                return function(bot, message)

            return wrapper

        return decorator
