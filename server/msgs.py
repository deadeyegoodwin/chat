#
# Copyright 2015 David Goodwin. All rights reserved.
#
import logging
from enum import Enum

class CserverCmd(Enum):
    """The commands send from the server to the CserverClient instances
    representing each connection chat client. These commands direct
    the client to update state and/or send messages to the chat
    client.

    """
    NEW_CLIENT = 1,
    BANNER = 2,
    LOGIN = 3,
    MSG = 4,
    EXISTING_USER = 5,
    INVALID_USERNAME = 6,
    WELCOME_USER = 7,
    SHOW_ROOMS = 8,
    CREATE_ROOM = 9,
    SEE_CREATE_ROOM = 10,
    JOIN_ROOM = 11,
    SEE_JOIN_ROOM = 12,
    LEAVE_ROOM = 13,
    SEE_LEAVE_ROOM = 14,
    INVALID_ROOM = 15,
    EXISTING_ROOM = 16,
    NOT_IN_ROOM = 17,
    INVALID_ROOMNAME = 18,
    PRIVATE = 19,
    PUBLIC = 20,
    INVALID_PRIVATE = 21,
    INVALID_CMD = 22,
    QUIT = 23

class CserverMsgKind(Enum):
    """Types of messages delivered by a CserverClient to the server. Each
    type represents a chat command or chat message entered by the chat
    user.

    """
    ALL_CHAT = 0,
    PRIVATE_CMD = 1,
    PUBLIC_CMD = 2,
    CREATE_ROOM_CMD = 3,
    ROOMS_CMD = 4,
    JOIN_CMD = 5,
    LEAVE_CMD = 6,
    QUIT_CMD = 7,
    UNKNOWN_CMD = 8

def decode_msg(msg):
    """Return the CserverMsgKind value and payload corresponding to a chat
    message.

    Args:
    
    msg (str): the message

    Return a tuple of CserverMsgKind and payload (str)

    """
    msg = msg.strip()
    if msg.startswith('/create'):
        payload = msg[len('/create'):]
        return (CserverMsgKind.CREATE_ROOM_CMD, payload.strip())
    elif msg.startswith('/rooms'):
        return (CserverMsgKind.ROOMS_CMD, None)
    elif msg.startswith('/join'):
        payload = msg[len('/join'):]
        return (CserverMsgKind.JOIN_CMD, payload.strip())
    elif msg.startswith('/leave'):
        return (CserverMsgKind.LEAVE_CMD, None)
    elif msg.startswith('/quit'):
        return (CserverMsgKind.QUIT_CMD, None)
    elif msg.startswith('/private'):
        payload = msg[len('/private'):]
        return (CserverMsgKind.PRIVATE_CMD, payload.strip().split())
    elif msg.startswith('/public'):
        return (CserverMsgKind.PUBLIC_CMD, None)
    elif msg.startswith('/'):
        return (CserverMsgKind.UNKNOWN_CMD, None)

    return (CserverMsgKind.ALL_CHAT, msg)


