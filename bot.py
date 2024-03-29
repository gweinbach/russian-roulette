from gevent import monkey
monkey.patch_all()

import os
import logging
from gevent import sleep
from random import randint
from dotenv import load_dotenv
from discord import Bot, Message, User

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(name)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

ONE_HOUR = 60 * 60
BULLETS_COUNT = 6
WIN_POINTS_REWARD = 1
DEATH_POINTS_PENALTY = 3
PLAYER_POINTS_FORMAT = "roulette.{user_id}"
BOT_TOKEN_ENVIRONMENT_VARIABLE_NAME = "DISCORD_ROULETTE_BOT_TOKEN"


class RouletteBot(Bot):
    @Bot.register_command("!roulette", cooldown=ONE_HOUR)
    def handle_roulette_command(self, message: Message):
        message.respond(f"😣🔫 {message.author.mention()} places the muzzle against their head...")
        sleep(3)
        if randint(0, BULLETS_COUNT) == 0:
            self.kv.decrement_int(self.__player_score_key(message.author), DEATH_POINTS_PENALTY)
            message.respond(f"☠ {message.author.mention()} dies and loses {DEATH_POINTS_PENALTY}!")
        else:
            self.kv.increment_int(self.__player_score_key(message.author), WIN_POINTS_REWARD)
            message.respond(f"🥵 {message.author.mention()} lives and wins **{WIN_POINTS_REWARD} points**!")

    @Bot.register_command("!points")
    def handle_points_command(self, message: Message):
        points = self.kv.get_int(self.__player_score_key(message.author), default=0)
        message.respond(f"{message.author.mention()}, you have **{points} points**!")

    @staticmethod
    def __player_score_key(user: User):
        return PLAYER_POINTS_FORMAT.format(user_id=user.id)


if __name__ == "__main__":

    load_dotenv()

    bot_token = os.environ.get(BOT_TOKEN_ENVIRONMENT_VARIABLE_NAME)
    if not bot_token:
        logger.error(f"Token is not defined. Please set '{BOT_TOKEN_ENVIRONMENT_VARIABLE_NAME}' environment variable")
        exit(1)

    bot = RouletteBot(bot_token)
    RouletteBot.run_forever()
