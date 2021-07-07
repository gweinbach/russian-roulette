import logging
from typing import Optional, Callable

import gevent
from gevent import Greenlet

logger = logging.getLogger(__name__)


class Callback:

    def __init__(self,
                 caller: object,
                 callback_function: Callable,
                 rearm_timeout_in_s: int = 0):
        self.caller = caller
        self.callback_function = callback_function
        self.rearm_timeout_in_s = rearm_timeout_in_s
        self.disarmed_users = {}

    def _disarm_user(self,
                     user_id: str) -> None:
        if user_id and self.rearm_timeout_in_s > 0:
            logger.debug(f"disarming callback {self} for user {user_id} during {self.rearm_timeout_in_s}s")
            self.disarmed_users[user_id] = gevent.spawn(lambda: gevent.sleep(self.rearm_timeout_in_s))

    def _is_user_armed(self,
                       user_id: str) -> bool:
        if not user_id:
            return True
        else:
            disarmed_user = self.disarmed_users.get(user_id, None)
            logger.debug(f"is callback {self} for user{user_id} armed ? {(not disarmed_user) or disarmed_user.dead}")
            return (not disarmed_user) or disarmed_user.dead

    def fire(self,
             *args,
             user_id: str = None) -> Optional[Greenlet]:
        if self._is_user_armed(user_id):
            self._disarm_user(user_id)
            return gevent.spawn(self.callback_function, self.caller, *args)

    def __str__(self) -> str:
        return f"{self.caller.__class__.__name__}.{self.callback_function.__name__}"

    def __eq__(self, other):
        return isinstance(other, Callback) and \
               other.caller == self.caller and \
               other.callback_function == self.callback_function and \
               other.rearm_timeout_in_s == self.rearm_timeout_in_s

    def __hash__(self):
        return hash(self.caller) ^ \
               hash(self.callback_function) >> 1 ^ \
               hash(self.rearm_timeout_in_s) >> 2


class CallbackHolder:

    def __init__(self):
        self._callback_registry = {}

    def register_callback(self,
                          key: str,
                          caller: object,
                          callback_method,
                          rearm_timeout_in_s: int = 0) -> None:
        logger.info(f"registered {caller}.{callback_method} to handle {key}")
        self._callback_registry[key] = Callback(caller, callback_method, rearm_timeout_in_s)

    def matching_callback(self,
                          key_value: str) -> Optional[Callback]:
        return self._callback_registry.get(key_value, None)
