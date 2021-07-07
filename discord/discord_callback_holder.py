import logging
from typing import Optional

import gevent
from gevent import Greenlet

logger = logging.getLogger(__name__)

class DiscordCallback(object):
    def __init__(self,
                 caller: object,
                 callback_function,
                 rearm_timeout_in_s: int = 0):
        self.caller = caller
        self.callback_function = callback_function
        self.rearm_timeout_in_s = rearm_timeout_in_s
        self.disarmed_users = {}

    def disarm_user(self,
                    user_id: str) -> None:
        logger.debug(f"disarming callback {self} for user {user_id} during {self.rearm_timeout_in_s}s")
        self.disarmed_users[user_id] = gevent.spawn(lambda: gevent.sleep(self.rearm_timeout_in_s))

    def is_user_armed(self,
                      user_id: str) -> bool:
        disarmed_user = self.disarmed_users.get(user_id, None)
        logger.debug(f"is callback {self} for user{user_id} armed ? {(not disarmed_user) or disarmed_user.dead}")
        return (not disarmed_user) or disarmed_user.dead

    def fire(self,
             message: any) -> Optional[Greenlet]:
        user_id = message.author.id
        if self.is_user_armed(user_id):
            self.disarm_user(user_id)
            return gevent.spawn(self.callback_function, self.caller, message)

    def __str__(self) -> str:
        return f"{self.caller.__class__.__name__}.{self.callback_function.__name__}"


class DiscordCallbackHolder():
    def __init__(self):
        self.callback_registry = {}

    def register_callback(self,
                          message_content: str,
                          caller: object,
                          callback_function,
                          rearm_timeout_in_s: int = 0) -> None:
        logger.info(f"registered {caller}.{callback_function} to handle {message_content}")
        self.callback_registry[message_content] = DiscordCallback(caller, callback_function, rearm_timeout_in_s)

    def matching_callback(self,
                          message_content: str) -> Optional[DiscordCallback]:
        return self.callback_registry.get(message_content, None)
