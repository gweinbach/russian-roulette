from __future__ import annotations

import copy
import json
import logging
import sys
from collections import Sequence
from datetime import datetime
from enum import Enum, IntEnum
from random import random
from typing import Optional

import gevent
import requests
from gevent import Greenlet
from gevent.event import Event
from gevent.queue import Queue
from pytz import utc
from ws4py.client.geventclient import WebSocketClient

from .discord_callback_holder import DiscordCallbackHolder
from .user import User

logger = logging.getLogger(__name__)

DISCORD_API_CLIENT_VERSION = "0.1"
DISCORD_API_CLIENT_URL = "https://github.com/gweinbach/russian-roulette"
DISCORD_API_LIB_NAME = "discord_client.py"

DISCORD_API_VERSION = "9"
DISCORD_GATEWAY_API_VERSION = "9"

DISCORD_API_BASE_URL = "https://discord.com/api"
DISCORD_GATEWAY_PATH = "/gateway/bot"
DISCORD_CURRENT_USER_PATH = "/users/@me"
DISCORD_CREATE_MESSAGE_PATH = "/channels/{channel_id}/messages"

DISCORD_AUTHORIZATION_HEADER = "Bot {token}"
DISCORD_USER_AGENT_HEADER = f"DiscordBot ({DISCORD_API_CLIENT_URL}, {DISCORD_API_CLIENT_VERSION})"


# Exceptions
class DiscordError(Exception):
    pass


class DiscordGatewayConnectionError(DiscordError):
    def __init__(self, message):
        self.message = message
        super().__init__(self.message)


class DiscordEmptyGatewayOperation(DiscordError):
    pass


class DiscordUnknownGatewayOperation(DiscordError):
    def __init__(self, op):
        self.op = op
        super().__init__(f"Invalid operation. Operation Code {op} is not implemented")


class DiscordInvalidGatewayOperation(DiscordError):
    def __init__(self, op, expected_op):
        self.op = op
        self.expected_op = expected_op
        super().__init__(f"Invalid operation. Expected {expected_op} but actual Operation Code is {op}")


# Enums
class DiscordMessageType(IntEnum):
    DEFAULT = 0
    RECIPIENT_ADD = 1
    RECIPIENT_REMOVE = 2
    CALL = 3
    CHANNEL_NAME_CHANGE = 4
    CHANNEL_ICON_CHANGE = 5
    CHANNEL_PINNED_MESSAGE = 6
    GUILD_MEMBER_JOIN = 7
    USER_PREMIUM_GUILD_SUBSCRIPTION = 8
    USER_PREMIUM_GUILD_SUBSCRIPTION_TIER_1 = 9
    USER_PREMIUM_GUILD_SUBSCRIPTION_TIER_2 = 10
    USER_PREMIUM_GUILD_SUBSCRIPTION_TIER_3 = 11
    CHANNEL_FOLLOW_ADD = 12
    GUILD_DISCOVERY_DISQUALIFIED = 14
    GUILD_DISCOVERY_REQUALIFIED = 15
    GUILD_DISCOVERY_GRACE_PERIOD_INITIAL_WARNING = 16
    GUILD_DISCOVERY_GRACE_PERIOD_FINAL_WARNING = 17
    THREAD_CREATED = 18
    REPLY = 19
    APPLICATION_COMMAND = 20
    THREAD_STARTER_MESSAGE = 21
    GUILD_INVITE_REMINDER = 22


class DiscordGatewayOpCode(IntEnum):
    NO_OP = -1
    DISPATCH = 0
    HEARTBEAT = 1
    IDENTIFY = 2
    PRESENCE = 3
    VOICE_STATE = 4
    VOICE_PING = 5
    RESUME = 6
    RECONNECT = 7
    REQUEST_MEMBERS = 8
    INVALIDATE_SESSION = 9
    HELLO = 10
    HEARTBEAT_ACK = 11
    GUILD_SYNC = 12


class DiscordGatewayEventName(Enum):
    Unknown = None
    Ready = "READY"
    MessageCreate = "MESSAGE_CREATE"


class DiscordGatewayIntent(IntEnum):
    Guilds = 1 << 0
    GuildMembers = 1 << 1
    GuildBans = 1 << 2
    GuildEmokis = 1 << 3
    GuildIntegrations = 1 << 4
    GuildWebhooks = 1 << 5
    GuildInvites = 1 << 6
    GuildVoiceStates = 1 << 7
    GuildPresences = 1 << 8
    GuildMessages = 1 << 9
    GuildMessageReactions = 1 << 10
    GuildMessageTyping = 1 << 11
    DirectMessages = 1 << 12
    DirectMessageReactions = 1 << 13
    DirectMessageTyping = 1 << 14


# Gateway Operations Hierarchy
class DiscordGatewayOp():
    _last_message_seq: Optional[int] = None

    def __init__(self,
                 op_code: DiscordGatewayOpCode,
                 operation: dict):
        self.op_code = op_code
        self.operation = operation
        self.check_type()

    def op(self) -> DiscordGatewayOpCode:
        if isinstance(self.operation, dict):
            return DiscordGatewayOpCode(self.operation.get("op", DiscordGatewayOpCode.NO_OP.value))
        else:
            return DiscordGatewayOpCode.NO_OP

    def sequence_number(self) -> Optional[int]:
        if isinstance(self.operation, dict):
            return self.operation.get("s", None)
        else:
            return None

    def event_name(self) -> DiscordGatewayEventName:
        if isinstance(self.operation, dict):
            return DiscordGatewayEventName(self.operation.get("t", DiscordGatewayEventName.Unknown.value))
        else:
            return DiscordGatewayEventName.Unknown

    def event_data(self) -> dict:
        if isinstance(self.operation, dict):
            return self.operation.get("d", {})
        else:
            return {}

    def has_type(self) -> bool:
        return self.op() == self.op_code

    def check_type(self) -> None:
        if not self.has_type():
            raise DiscordInvalidGatewayOperation(self.operation, self.op_code)
        else:
            pass

    def handle_event(self,
                     discord_client: DiscordClient) -> Optional[Greenlet]:
        logger.info(f"Nothing has to be done to handle event on Gateway operation {self.__class__.__name__}")
        return None

    @classmethod
    def expect(cls,
               message: str):
        if not message:
            raise DiscordEmptyGatewayOperation()
        payload = json.loads(message)
        DiscordGatewayOp._last_message_seq = payload.get("s", None)

        return cls(DiscordGatewayOpCode(payload.get("op", DiscordGatewayOpCode.NO_OP.value)), payload)

    @staticmethod
    def receive(message: str) -> DiscordGatewayOp:
        if not message:
            raise DiscordEmptyGatewayOperation()
        payload = json.loads(message)
        DiscordGatewayOp.set_last_message_seq(payload.get("s", None))

        op_code = payload.get("op", DiscordGatewayOpCode.NO_OP.value)
        op_class = DISCORD_OP_TO_CLASS.get(op_code)
        if op_class is None:
            raise DiscordUnknownGatewayOperation(op_code)

        return op_class(DiscordGatewayOpCode(payload.get("op", DiscordGatewayOpCode.NO_OP.value)), payload)

    # This method has no return type annotation because prior to 3.10,
    # you cannot use given class type as return class type in a class method
    @classmethod
    def _create(cls,
                op_code: DiscordGatewayOpCode,
                content: dict):
        return cls(
            op_code,
            dict(copy.deepcopy(content), op=op_code.value)
        )

    @staticmethod
    def last_message_seq() -> Optional[int]:
        last_message_seq = None
        if hasattr(DiscordGatewayOp, '_last_message_seq'):
            last_message_seq = DiscordGatewayOp._last_message_seq
        return last_message_seq

    @staticmethod
    def set_last_message_seq(seq: int) -> None:
        if seq is not None:
            DiscordGatewayOp._last_message_seq = seq

    def json(self) -> str:
        return json.dumps(self.operation)

    def __str__(self) -> str:
        return self.json()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.op_code}, {self.operation})"


class DiscordGatewayDispatch(DiscordGatewayOp):

    @classmethod
    def create(cls,
               event: dict) -> DiscordGatewayDispatch:
        return cls._create(
            DiscordGatewayOpCode.DISPATCH,
            {
                "d": copy.deepcopy(event)
            }
        )

    def handle_event(self,
                     discord_client: DiscordClient) -> Optional[Greenlet]:
        user = self._build_user_from_event_author()

        if user:
            event_data = self.event_data()
            message_content = event_data.get("content", "")

            callback = discord_client.matching_callback(message_content)

            if callback:
                logger.info(f"found callback matching message content ({message_content}): {callback}")

                message_id = event_data.get("id", "")
                message = Message(message_id, user, message_content, self, discord_client)

                return callback.fire(message)

    def _build_user_from_event_author(self) -> Optional[User]:
        user = self.event_data().get("author", {})
        user_id = user.get("id", "")
        user_name = user.get("username", "")
        if user_id:
            return User(user_id, user_name)
        else:
            return None


class DiscordGatewayHeartbeatAck(DiscordGatewayOp):

    @classmethod
    def create(cls,
               event: dict) -> DiscordGatewayHeartbeatAck:
        return cls._create(
            DiscordGatewayOpCode.HEARTBEAT_ACK,
            {}
        )

    def handle_event(self, discord_client: DiscordClient) -> Optional[Greenlet]:
        discord_client.heartbeat_on()
        return None


class DiscordGatewayCommand(DiscordGatewayOp):

    def check_type(self):
        if self.event_name() != DiscordGatewayEventName.Unknown or self.sequence_number():
            raise DiscordInvalidGatewayOperation(self.operation, self.op_code)
        super().check_type()


class DiscordGatewayHello(DiscordGatewayCommand):

    @property
    def heartbeat_interval(self) -> int:
        if isinstance(self.operation, dict):
            return self.operation.get("d", {}).get("heartbeat_interval", 0)
        else:
            return 0

    @classmethod
    def create(cls,
               token: str) -> DiscordGatewayHello:
        return cls._create(
            DiscordGatewayOpCode.HELLO,
            {
                "d": {
                    "heartbeat_interval": 45000
                }
            }
        )


class DiscordGatewayHeartbeat(DiscordGatewayCommand):

    def last_message_seq_data(self) -> Optional[int]:
        if isinstance(self.operation, dict):
            return self.operation.get("d", None)
        else:
            return None

    @classmethod
    def create(cls) -> DiscordGatewayHeartbeat:
        return cls._create(
            DiscordGatewayOpCode.HEARTBEAT,
            {
                "d": DiscordGatewayOp.last_message_seq()
            }
        )


class DiscordGatewayIdentify(DiscordGatewayCommand):

    @classmethod
    def create(cls,
               token: str,
               intents: int) -> DiscordGatewayIdentify:
        return cls._create(
            DiscordGatewayOpCode.IDENTIFY,
            {
                "d": {
                    "token": token,
                    "intents": intents,
                    "properties": {
                        "$os": sys.platform,
                        "$browser": DISCORD_API_LIB_NAME,
                        "$device": DISCORD_API_LIB_NAME
                    }
                }
            }
        )


DISCORD_OP_TO_CLASS = {
    DiscordGatewayOpCode.NO_OP: None,
    DiscordGatewayOpCode.DISPATCH: DiscordGatewayDispatch,
    DiscordGatewayOpCode.HEARTBEAT: DiscordGatewayHeartbeat,
    DiscordGatewayOpCode.IDENTIFY: DiscordGatewayIdentify,
    DiscordGatewayOpCode.PRESENCE: None,
    DiscordGatewayOpCode.VOICE_STATE: None,
    DiscordGatewayOpCode.VOICE_PING: None,
    DiscordGatewayOpCode.RESUME: None,
    DiscordGatewayOpCode.RECONNECT: None,
    DiscordGatewayOpCode.REQUEST_MEMBERS: None,
    DiscordGatewayOpCode.INVALIDATE_SESSION: None,
    DiscordGatewayOpCode.HELLO: DiscordGatewayHello,
    DiscordGatewayOpCode.HEARTBEAT_ACK: DiscordGatewayHeartbeatAck,
    DiscordGatewayOpCode.GUILD_SYNC: None,
}


class Message:

    def __init__(self,
                 id: str,
                 author: User,
                 content: str,
                 original_event: DiscordGatewayOp,
                 discord_client: DiscordClient):
        self.id = id
        self.author = author
        self.content = content
        self.original_event = original_event
        self.discord_client = discord_client
        logger.info(self)

    def respond(self, response: str) -> Greenlet:
        logger.debug(f"responding {response}")
        return self.discord_client.respond_with(response, request=self.original_event)



class DiscordClient(DiscordCallbackHolder):

    def __init__(self,
                 token: str,
                 api_version=DISCORD_API_VERSION,
                 gateway_api_version=DISCORD_GATEWAY_API_VERSION):
        
        self.token = token
        self.api_version = api_version
        self.gateway_api_version = gateway_api_version

        self.connected_to_gateway_event = Event()
        self.heartbeat_event = Event()
        self.event_queue = Queue()
        self.websocket = None
        
        super().__init__()

    @property
    def bot_authorization_header(self) -> str:
        return DISCORD_AUTHORIZATION_HEADER.format(token=self.token)

    @property
    def user_agent_header(self) -> str:
        return DISCORD_USER_AGENT_HEADER

    @property
    def header(self) -> dict:
        return {
            'user-agent': self.user_agent_header,
            'authorization': self.bot_authorization_header,
            'content-type': 'application/json'
        }

    @property
    def api_base_url(self) -> str:
        return f"{DISCORD_API_BASE_URL}/v{self.api_version}"

    def api_url(self,
                ressource_path: str) -> str:
        return f"{self.api_base_url}{ressource_path}"

    @property
    def gateway_base_url(self) -> str:
        result = requests.get(
            url=self.api_url(ressource_path=DISCORD_GATEWAY_PATH),
            headers=self.header
        )
        return result.json()["url"] + f"?v={self.gateway_api_version}&encoding=json"

    @property
    def me(self) -> dict:
        result = requests.get(
            url=self.api_url(ressource_path=DISCORD_CURRENT_USER_PATH),
            headers=self.header
        )
        return result.json()

    def connect_to_gateway(self) -> None:

        uri = self.gateway_base_url
        self.websocket = Ws4pyClient(uri)

        hello = DiscordGatewayHello.expect(self.websocket.receive())

        # starting heartbeat loop
        heartbeat_interval = hello.heartbeat_interval
        heartbeat = gevent.spawn(self.heartbeat, interval=heartbeat_interval)
        self.heartbeat_on()

        identify = DiscordGatewayIdentify.create(self.token,
                                                 DiscordGatewayIntent.GuildMessages | DiscordGatewayIntent.GuildMessageReactions | DiscordGatewayIntent.DirectMessages | DiscordGatewayIntent.DirectMessageReactions)
        self.websocket.send(identify)

        ready = DiscordGatewayDispatch.expect(self.websocket.receive())

        # Signals that connection is OK
        self.connected_to_gateway_event.set()

        heartbeat.join()

    def heartbeat_on(self) -> None:
        self.heartbeat_event.set()

    def heartbeat_off(self) -> None:
        self.heartbeat_event.clear()

    def heartbeat(self,
                  interval: int) -> None:
        while True:
            self.heartbeat_event.wait()
            gevent.sleep((interval * random()) / 1000)
            logger.info("heartbeat!")
            heartbeat = DiscordGatewayHeartbeat.create()
            self.websocket.send(heartbeat)
            self.heartbeat_off()

    def queue_events(self) -> None:
        self.connected_to_gateway_event.wait()
        logger.info("queuing events...")
        while True:
            event = DiscordGatewayOp.receive(self.websocket.receive())
            self.event_queue.put(event)
            gevent.sleep(0)

    def handle_events(self) -> None:
        self.connected_to_gateway_event.wait()
        logger.info("...unqueuing events")
        while True:
            event = self.event_queue.get()
            gevent.spawn(event.handle_event, self)
            gevent.sleep(0)

    def respond_with(self,
                     response: str,
                     request: DiscordGatewayOp) -> Greenlet:

        def respond(message: dict):
            channel_id = message.get("channel_id", "0")
            user = self.me
            message["author"] = user

            logger.debug(f"respond message=${message}")
            result = requests.post(
                url=self.api_url(ressource_path=DISCORD_CREATE_MESSAGE_PATH.format(channel_id=channel_id)),
                headers=self.header,
                json=message
            )
            logger.debug(f"respond result={result}, reason={result.reason}, content={result.text}")

        request_message = request.event_data()
        response_message = copy.deepcopy(request_message)
        response_message["id"] = None
        response_message["timestamp"] = self.timestamp()
        response_message["content"] = response
        response_message["referenced_message"] = request_message
        response_message["message_reference"] = {
            "message_id": request_message["id"]
        }
        response_message["type"] = DiscordMessageType.REPLY.value

        return gevent.spawn(respond, response_message)

    def start(self) -> Sequence[Greenlet]:
        return [
            gevent.spawn(self.connect_to_gateway),
            gevent.spawn(self.queue_events),
            gevent.spawn(self.handle_events)
        ]

    @staticmethod
    def timestamp() -> str:
        return datetime.now().astimezone(utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00)")


class Ws4pyClient:

    def __init__(self, uri: str):
        self.ws = WebSocketClient(uri)
        self.ws.connect()

    def send(self, command: DiscordGatewayCommand) -> None:
        logger.info(f"> sending command {command}")
        self.ws.send(str(command))

    def receive(self) -> str:
        received = str(self.ws.receive())
        logger.info(f"< received message {received}")
        return received

#
# client = DiscordClient(token="ODYwMTk2NDMzMzY1NTY1NTAw.YN3uWw.DcaWW6jKiffaIVpi9uS3rZZ7QCM")
# api_url = client.api_base_url()
# gateway_endpoint = client.api_url(ressource_path=DISCORD_GATEWAY_PATH)
# wsurl = client.gateway_base_url()
#
# event = client.connect_to_gateway()
# print(event.event_name())
# print(event.event_data())
