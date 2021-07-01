from gevent import sleep
from discord import Bot, Message

ONE_HOUR = 60 * 60
BULLETS_COUNT = 6
WIN_POINTS_REWARD = 1
DEATH_POINTS_PENALTY = 3
PLAYER_POINTS_FORMAT = "roulette.{user_id}"

class RouletteBot(Bot):
    @Bot.register_command("!roulette", cooldown=ONE_HOUR)
    def handle_roulette_command(self, message: Message):
        message.respond(f"😣🔫 {message.author.mention()} places the muzzle against their head...")
        sleep(3)
        if randint(BULLETS_COUNT) == 0:
            self.kv.decrement_int(PLAYER_POINTS_FORMAT.format(user_id=message.author.id), DEATH_POINTS_PENALTY)
            message.respond(f"☠ {message.author.mention()} dies and loses {DEATH_POINTS_PENALTY}!")
        else:
            self.kv.increment_int(PLAYER_POINTS_FORMAT.format(user_id=message.author.id), WIN_POINTS_REWARD)
            message.respond(f"🥵 {message.author.mention()} lives and wins **{WIN_POINTS_REWARD} points**!")

    @Bot.register_command("!points")
    def handle_points_command(self, message: Message):
        points = self.kv.get_int(PLAYER_POINTS_FORMAT.format(user_id=message.author.id), default=0)
        message.respond(f"{message.author.mention()}, you have **{points} points**!")


if __name__ == "__main__":
    BOT_TOKEN = "CHANGE_ME"
    bot = RouletteBot(BOT_TOKEN)
    RouletteBot.run_forever()
