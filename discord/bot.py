import logging

import gevent

from .discord_client import DiscordClient, Message


class IntDictionary:

    def __init__(self):
        self.dict = {}

    def increment_int(self, key, int_value: int):
        self.dict[key] = self.dict.get(key, 0) + int_value

    def decrement_int(self, key, int_value: int):
        self.dict[key] = self.dict.get(key, 0) - int_value

    def get_int(self, key, default: int = 0):
        return self.dict.get(key, default)



bots = {}

registered_commands = {}

class CommandCallback:
    def __init__(self, callback_method, cooldown: int):
        self.callback_method = callback_method
        self.cooldown = cooldown

class Bot:
    def __init__(self, token: str):
        self.token = token
        self.kv = IntDictionary()
        self.discord_client = DiscordClient(token=token)

        [self.discord_client.register_callback(content, self, callback.callback_method, callback.cooldown) for (content, callback) in registered_commands.items()]
        bots[token] = self
        logging.info("Created a bot:", self)

    def run(self):
        gevent.joinall(self.discord_client.start())

    @staticmethod
    def run_forever():
        logging.info("Running bot loop")
        [bot.run() for bot in bots.values()]

    @staticmethod
    def register_command(command_name, cooldown: int = 0):

        def decorator(function):
            logging.info(f"I am the decorator of function {function}")
            def wrapper(bot: Bot, message: Message):
                logging.info(f"Bot {bot} is receiving message {message} related to command {command_name}")
                return function(bot, message)

            return wrapper

        registered_commands[command_name] = CommandCallback(callback_method = decorator, cooldown = cooldown)
        logging.info(f"Registered command: {command_name} that cools down in {cooldown}")
        return decorator
