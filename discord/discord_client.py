import copy
import json
import logging
import sys
from datetime import datetime
from enum import Enum, IntEnum
from random import random

import gevent
import requests
from gevent.queue import Queue
from pytz import utc
from ws4py.client.geventclient import WebSocketClient

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


class DiscordClientApi:
    def matching_callback(self, message_content: str):
        return None

    def heartbeat_on(self):
        pass


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
class DiscordGatewayOp:

    def __init__(self,
                 op_code: DiscordGatewayOpCode,
                 operation: dict):
        self.op_code = op_code
        self.operation = operation
        self.check_type()

    def op(self):
        if isinstance(self.operation, dict):
            return DiscordGatewayOpCode(self.operation.get("op", DiscordGatewayOpCode.NO_OP.value))
        else:
            return DiscordGatewayOpCode.NO_OP

    def sequence_number(self):
        if isinstance(self.operation, dict):
            return self.operation.get("s", None)
        else:
            return None

    def event_name(self):
        if isinstance(self.operation, dict):
            return DiscordGatewayEventName(self.operation.get("t", DiscordGatewayEventName.Unknown.value))
        else:
            return DiscordGatewayEventName.Unknown

    def event_data(self):
        if isinstance(self.operation, dict):
            return self.operation.get("d", {})
        else:
            return {}

    def has_type(self):
        return self.op() == self.op_code

    def check_type(self):
        if not self.has_type():
            raise DiscordInvalidGatewayOperation(self.operation, self.op_code)
        else:
            pass

    def handle_event(self,
                     discord_client: DiscordClientApi):
        logger.info(f"Nothing has to be done to handle event on Gateway operation {self.__class__.__name__}")

    @classmethod
    def expect(cls,
               message: str):
        if not message:
            raise DiscordEmptyGatewayOperation()
        payload = json.loads(message)
        DiscordGatewayOp._last_message_seq = payload.get("s", None)

        return cls(DiscordGatewayOpCode(payload.get("op", DiscordGatewayOpCode.NO_OP.value)), payload)

    @staticmethod
    def receive(message: str):
        if not message:
            raise DiscordEmptyGatewayOperation()
        payload = json.loads(message)
        DiscordGatewayOp.set_last_message_seq(payload.get("s", None))

        op_code = payload.get("op", DiscordGatewayOpCode.NO_OP.value)
        op_class = DISCORD_OP_TO_CLASS.get(op_code)
        if op_class is None:
            raise DiscordUnknownGatewayOperation(op_code)

        return op_class(DiscordGatewayOpCode(payload.get("op", DiscordGatewayOpCode.NO_OP.value)), payload)

    @classmethod
    def create(cls,
               op_code: DiscordGatewayOpCode,
               content: dict):
        return cls(
            op_code,
            dict(copy.deepcopy(content), op=op_code.value)
        )

    @staticmethod
    def last_message_seq():
        last_message_seq = None
        if hasattr(DiscordGatewayOp, '_last_message_seq'):
            last_message_seq = DiscordGatewayOp._last_message_seq
        return last_message_seq

    @staticmethod
    def set_last_message_seq(seq: int):
        if seq is not None:
            DiscordGatewayOp._last_message_seq = seq

    def json(self):
        return json.dumps(self.operation)

    def __str__(self):
        return self.json()

    def __repr__(self):
        return f"{self.__class__.__name__}({self.op_code}, {self.operation})"


class DiscordGatewayDispatch(DiscordGatewayOp):

    @classmethod
    def create(cls,
               event: dict):
        return super().create(
            DiscordGatewayOpCode.DISPATCH,
            {
                "d": copy.deepcopy(event)
            }
        )

    def handle_event(self,
                     discord_client: DiscordClientApi):
        event_data = self.event_data()
        message_content = event_data.get("content", "")
        callback = discord_client.matching_callback(message_content)

        if callback:
            logger.info(f"found callback matching message content ({message_content}): {callback}")

            message_id = event_data.get("id", "")
            user = event_data.get("author", {})
            user_id = user.get("id", "")
            user_name = user.get("username", "")

            message = Message(message_id, User(user_id, user_name), message_content, self, discord_client)
            gevent.spawn(callback.callback_function, callback.caller, message)


class DiscordGatewayHeartbeatAck(DiscordGatewayOp):

    @classmethod
    def create(cls,
               event: dict):
        return super().create(
            DiscordGatewayOpCode.HEARTBEAT_ACK,
            {}
        )

    def handle_event(self, discord_client: DiscordClientApi):
        discord_client.heartbeat_on()


class DiscordGatewayCommand(DiscordGatewayOp):

    def check_type(self):
        if self.event_name() != DiscordGatewayEventName.Unknown or self.sequence_number():
            raise DiscordInvalidGatewayOperation(self.operation, self.op_code)
        super().check_type()


class DiscordGatewayHello(DiscordGatewayCommand):

    def heartbeat_interval(self):
        if isinstance(self.operation, dict):
            return self.operation.get("d", {}).get("heartbeat_interval", 0)
        else:
            return 0

    @classmethod
    def create(cls,
               token: str):
        return super().create(
            DiscordGatewayOpCode.HELLO,
            {
                "d": {
                    "heartbeat_interval": 45000
                }
            }
        )


class DiscordGatewayHeartbeat(DiscordGatewayCommand):

    def last_message_seq_data(self):
        if isinstance(self.operation, dict):
            return self.operation.get("d", None)
        else:
            return None

    @classmethod
    def create(cls,
               token: str):
        return super().create(
            DiscordGatewayOpCode.HEARTBEAT,
            {
                "d": DiscordGatewayOp.last_message_seq()
            }
        )

    def handle_event(self,
                     discord_client: DiscordClientApi):
        super().handle_event(discord_client)


class DiscordGatewayIdentify(DiscordGatewayCommand):

    @classmethod
    def create(cls,
               token: str,
               intents: int):
        return super().create(
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


class DiscordCallback():
    def __init__(self,
                 caller: object,
                 callback_function,
                 cooldown: int = 0):
        self.caller = caller
        self.callback_function = callback_function
        self.cooldown = cooldown


class DiscordClient(DiscordClientApi):

    def __init__(self,
                 token: str,
                 api_version=DISCORD_API_VERSION,
                 gateway_api_version=DISCORD_GATEWAY_API_VERSION):
        self.token = token
        self.api_version = api_version
        self.gateway_api_version = gateway_api_version

        self.callback_registry = {}
        self.connected_to_gateway_event = gevent.event.Event()
        self.heartbeat_event = gevent.event.Event()
        self.event_queue = Queue()
        self.websocket = None

    def register_callback(self, message_content: str, caller: object, callback_function, cooldown: int = 0):
        logger.info(f"registered {caller}.{callback_function} to handle {message_content}")
        self.callback_registry[message_content] = DiscordCallback(caller, callback_function, cooldown)

    def matching_callback(self, message_content: str):
        return self.callback_registry.get(message_content, None)

    def bot_authorization_header(self):
        return DISCORD_AUTHORIZATION_HEADER.format(token=self.token)

    def user_agent_header(self):
        return DISCORD_USER_AGENT_HEADER

    def header(self):
        return {
            'user-agent': self.user_agent_header(),
            'authorization': self.bot_authorization_header(),
            'content-type': 'application/json'
        }

    def api_base_url(self):
        return f"{DISCORD_API_BASE_URL}/v{self.api_version}"

    def api_url(self, ressource_path: str):
        return f"{self.api_base_url()}{ressource_path}"

    def gateway_base_url(self):
        result = requests.get(
            url=self.api_url(ressource_path=DISCORD_GATEWAY_PATH),
            headers=self.header()
        )
        return result.json()["url"] + f"?v={self.gateway_api_version}&encoding=json"

    def me(self):
        result = requests.get(
            url=self.api_url(ressource_path=DISCORD_CURRENT_USER_PATH),
            headers=self.header()
        )
        return result.json()

    def connect_to_gateway(self):

        uri = self.gateway_base_url()
        self.websocket = Ws4pyClient(uri)

        hello = DiscordGatewayHello.expect(self.websocket.receive())

        # starting heartbeat loop
        heartbeat_interval = hello.heartbeat_interval()
        heartbeat = gevent.spawn(self.heartbeat, interval=heartbeat_interval)
        self.heartbeat_on()

        self.websocket.send(DiscordGatewayIdentify.create(self.token,
                                                          DiscordGatewayIntent.GuildMessages | DiscordGatewayIntent.GuildMessageReactions | DiscordGatewayIntent.DirectMessages | DiscordGatewayIntent.DirectMessageReactions))

        ready = DiscordGatewayDispatch.expect(self.websocket.receive())

        # Signals that connection is OK
        self.connected_to_gateway_event.set()

        heartbeat.join()

    def heartbeat_on(self):
        self.heartbeat_event.set()

    def heartbeat_off(self):
        self.heartbeat_event.clear()

    def heartbeat(self,
                  interval: int):
        self.heartbeat_event.wait()
        gevent.sleep((interval * random()) / 1000)
        logger.info("heartbeat!")
        heartbeat = DiscordGatewayHeartbeat.create(self.token)
        self.websocket.send(heartbeat)
        self.heartbeat_off()
        self.heartbeat(interval)

    def queue_events(self):
        self.connected_to_gateway_event.wait()
        logger.info("queuing events...")
        while True:
            event = DiscordGatewayOp.receive(self.websocket.receive())
            self.event_queue.put(event)
            gevent.sleep(0)

    def handle_events(self):
        self.connected_to_gateway_event.wait()
        logger.info("...unqueuing events")
        while True:
            event = self.event_queue.get()
            gevent.spawn(event.handle_event, self)
            gevent.sleep(0)

    def respond_with(self,
                     response: str,
                     request: DiscordGatewayOp):

        def respond(message: dict):
            channel_id = message.get("channel_id", "0")
            user = self.me()
            message["author"] = user

            logger.debug(f"respond message=${message}")
            result = requests.post(
                url=self.api_url(ressource_path=DISCORD_CREATE_MESSAGE_PATH.format(channel_id=channel_id)),
                headers=self.header(),
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

        gevent.spawn(respond, response_message)

    def start(self):
        return [
            gevent.spawn(self.connect_to_gateway),
            gevent.spawn(self.queue_events),
            gevent.spawn(self.handle_events)
        ]

    @staticmethod
    def timestamp():
        return datetime.now().astimezone(utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00)")


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

    def respond(self, response: str):
        logger.info(f"responding {response}")
        print(type(self.original_event))
        self.discord_client.respond_with(response, request=self.original_event)


class Ws4pyClient:

    def __init__(self, uri: str):
        self.ws = WebSocketClient(uri)
        self.ws.connect()

    def send(self, command: DiscordGatewayCommand):
        logger.info(f"> sending command {command}")
        self.ws.send(str(command))

    def receive(self):
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
