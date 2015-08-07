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
    JOIN_ROOM = 9,
    SEE_JOIN_ROOM = 10,
    LEAVE_ROOM = 11,
    SEE_LEAVE_ROOM = 12,
    INVALID_ROOM = 13,
    NOT_IN_ROOM = 14,
    QUIT = 15

class CserverMsgKind(Enum):
    ALL_CHAT = 0,
    PRIVATE_CHAT = 1,
    ROOMS_CMD = 2,
    JOIN_CMD = 3,
    LEAVE_CMD = 4,
    QUIT_CMD = 5

def decode_msg(msg):
    """Return the CserverMsgKind value and payload corresponding to a message.

    Args:
    
    msg (str): the message

    Return a tuple of CserverMsgKind and payload (str)
    """
    msg = msg.strip()
    if msg.startswith('/rooms'):
        return (CserverMsgKind.ROOMS_CMD, None)
    elif msg.startswith('/join'):
        payload = msg[len('/join'):]
        return (CserverMsgKind.JOIN_CMD, payload.strip())
    elif msg.startswith('/leave'):
        return (CserverMsgKind.LEAVE_CMD, None)
    elif msg.startswith('/quit'):
        return (CserverMsgKind.QUIT_CMD, None)
    
    return (CserverMsgKind.ALL_CHAT, msg)


