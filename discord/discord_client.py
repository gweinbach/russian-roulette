import json
import logging
import sys
from enum import Enum, IntEnum

import gevent
import requests
from ws4py.client.geventclient import WebSocketClient

from .user import User

DISCORD_API_CLIENT_VERSION = "0.1"
DISCORD_API_CLIENT_URL = "https://github.com/gweinbach/russian-roulette"
DISCORD_API_LIB_NAME = "discord_client.py"

DISCORD_API_VERSION = "9"
DISCORD_GATEWAY_API_VERSION = "9"

DISCORD_API_BASE_URL = "https://discord.com/api"
DISCORD_GATEWAY_PATH = "gateway/bot"

DISCORD_AUTHORIZATION_HEADER = "Bot {token}"
DISCORD_USER_AGENT_HEADER = f"DiscordBot ({DISCORD_API_CLIENT_URL}, {DISCORD_API_CLIENT_VERSION})"


class DiscordError(Exception):
    pass


class DiscordConnectionError(DiscordError):
    def __init__(self, message):
        self.message = message
        super().__init__(self.message)


class DiscordInvalidOperation(DiscordError):
    def __init__(self, op, expected_op):
        self.op = op
        self.expected_op = expected_op
        super().__init__(f"Invalid operation. Expected {expected_op} but actual Operation Code is {op}")


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
            return self.operation.get("s", 0)
        else:
            return 0

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
            raise DiscordInvalidOperation(self.operation, self.op_code)
        else:
            pass

    @classmethod
    def received(cls,
                 message: str):
        if not message:
            raise DiscordInvalidOperation()
        payload = json.loads(message)
        return cls(DiscordGatewayOpCode(payload.get("op", DiscordGatewayOpCode.NO_OP.value)), payload)

    @classmethod
    def create(cls,
               op_code: DiscordGatewayOpCode,
               content: dict):
        return cls(
            op_code,
            dict(content.copy(), op=op_code.value)
        )

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
                "d": event
            }
        )


class DiscordGatewayCommand(DiscordGatewayOp):

    def check_type(self):
        if self.event_name() != DiscordGatewayEventName.Unknown or self.sequence_number():
            raise DiscordInvalidOperation(self.operation, self.op_code)
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


class DiscordCallback():
     def __init__(self,
                  caller: object,
                  callback_function,
                  cooldown: int = 0):
         self.caller = caller
         self.callback_function = callback_function
         self.cooldown = cooldown


class DiscordClient(object):

    def __init__(self,
                 token: str,
                 api_version=DISCORD_API_VERSION,
                 gateway_api_version=DISCORD_GATEWAY_API_VERSION):
        self.token = token
        self.api_version = api_version
        self.gateway_api_version = gateway_api_version

        self.message_handler_registry = {}
        self.connected_to_gateway_event = gevent.event.Event()
        self.websocket = None

    def register_callback(self, message_content: str, caller: object, callback_function, cooldown: int = 0):
        logging.info(f"registered {caller}.{callback_function} to handle {message_content}")
        self.message_handler_registry[message_content] = DiscordCallback(caller, callback_function, cooldown)

    def bot_authorization_header(self):
        return DISCORD_AUTHORIZATION_HEADER.format(token=self.token)

    def user_agent_header(self):
        return DISCORD_USER_AGENT_HEADER

    def header(self):
        return {
            'user-agent': self.user_agent_header(),
            'authorization': self.bot_authorization_header()
        }

    def api_base_url(self):
        return f"{DISCORD_API_BASE_URL}/v{self.api_version}"

    def api_url(self, ressource_path: str):
        return f"{self.api_base_url()}/{ressource_path}"

    def gateway_base_url(self):
        result = requests.get(
            url=self.api_url(ressource_path=DISCORD_GATEWAY_PATH),
            headers=self.header()
        )
        return result.json()["url"] + f"?v={self.gateway_api_version}&encoding=json"

    def connect_to_gateway(self):

        uri = self.gateway_base_url()
        self.websocket = Ws4pyClient(uri)

        hello = DiscordGatewayHello.received(self.websocket.receive())
        heartbeat_interval = hello.heartbeat_interval()
        heartbeat = gevent.spawn(self.heartbeat(heartbeat_interval))

        self.websocket.send(DiscordGatewayIdentify.create(self.token,
                                                          DiscordGatewayIntent.GuildMessages | DiscordGatewayIntent.GuildMessageReactions | DiscordGatewayIntent.DirectMessages | DiscordGatewayIntent.DirectMessageReactions))

        ready = DiscordGatewayDispatch.received(self.websocket.receive())

        # Signals that connection is OK
        self.connected_to_gateway_event.set()

        heartbeat.join()

    # TODO implement heartbeat
    def heartbeat(self, interval: int):
        pass

    def event_loop(self):
        self.connected_to_gateway_event.wait()
        while True:
            event = DiscordGatewayDispatch.received(self.websocket.receive())
            self.handle_event(event)
            gevent.sleep(0)


    def handle_event(self, event: dict):
        logging.info(f"handling event: {event}")

        event_data = event.event_data()
        message_content = event_data.get("content", "")
        callback = self.message_handler_registry.get(message_content, None)

        logging.info(f"found callback: {callback}")

        if (callback):

            message_id = event_data.get("id", "")
            user = event_data.get("author", {})
            user_id = user.get("id", "")
            user_name = user.get("username", "")

            message = Message(message_id, User(user_id, user_name), message_content, self)
            callback.callback_function(callback.caller, message)



    def start(self):
        return [
            gevent.spawn(self.connect_to_gateway()),
            gevent.spawn(self.event_loop())
        ]

class Message:

    def __init__(self,
                 id: str,
                 author: User,
                 content: str,
                 discord_client: DiscordClient):
        self.id = id
        self.author = author
        self.content = content
        self.discord_client = discord_client
        logging.info(self)

    # TODO implement message response
    def respond(self, response: str):
        logging.info(f"responding {response}")
        # self.discord_client.websocket.send()


class Ws4pyClient:

    def __init__(self, uri: str):
        self.ws = WebSocketClient(uri)
        self.ws.connect()

    def send(self, command: DiscordGatewayCommand):
        logging.info(f"> sending command {command}")
        self.ws.send(str(command))

    def receive(self):
        received = str(self.ws.receive())
        logging.info(f"< received message {received}")
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
