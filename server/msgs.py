#
# Copyright 2015 David Goodwin. All rights reserved.
#
import logging
from enum import Enum

class CserverCmd(Enum):
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
    QUIT = 18

class CserverMsgKind(Enum):
    ALL_CHAT = 0,
    PRIVATE_CHAT = 1,
    CREATE_ROOM_CMD = 2,
    ROOMS_CMD = 3,
    JOIN_CMD = 4,
    LEAVE_CMD = 5,
    QUIT_CMD = 6

def decode_msg(msg):
    """Return the CserverMsgKind value and payload corresponding to a message.

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
    
    return (CserverMsgKind.ALL_CHAT, msg)


