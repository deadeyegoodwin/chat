#
# Copyright 2015 David Goodwin. All rights reserved.
#
import logging
import queue
import socket
from enum import Enum
from msgs import CserverCmd
from threading import Thread

class CserverClientState(Enum):
    NEW = 1,
    LOGGED_IN = 2,
    IN_ROOM = 3

class CserverClient:
    """Handle interactions with a chat client. Each instance of this class
    runs two threads, one to handle input and one to handle output.

    Attributes:

    _csocket: the socket connecting to the client

    username (str): the name of the user currently logged in from
    this client, or None if no user logged in

    _recv_str (str): buffer to hold incoming client messages and chunk
    them into lines

    """
    def __init__(self, csocket, inbound_queue):
        '''Create an object to manage interaction with a client.

        Args:
        
        csocket: the socket connecting to the client

        inbound_queue (queue.Queue): the queue the client uses to
        communicate inbound activity

        '''
        self.state = CserverClientState.NEW
        self._csocket = csocket
        self.username = None
        self.roomname = None
        self.targets = None
        self._recv_str = ''
        self.outbound_queue = queue.Queue()
        self._inbound_queue = inbound_queue
        self._outbound_thread = Thread(target=CserverClient.outbound_handler, args=(self, ))
        self._inbound_thread = Thread(target=CserverClient.inbound_handler, args=(self,))
        self._outbound_thread.start()
        self._inbound_thread.start()

    def outbound_handler(self):
        """Handle all outgoing client traffic."""
        logging.info("starting client outbound_handler of socket {0}".format(self._csocket.getpeername()))

        try:
            while (True):
                # Queue contains tuples with the first element
                # indicating the kind. Use that to do the right thing.
                cmd = self.outbound_queue.get()
                logging.debug("outbound command {0}".format(cmd))
                try:
                    msg = None
                    if cmd[0] is CserverCmd.BANNER:
                        msg = (cmd[1],)
                    elif cmd[0] is CserverCmd.LOGIN:
                        msg = ("Login Name?",)
                    elif cmd[0] is CserverCmd.EXISTING_USER:
                        msg = ("Sorry, name taken.",)
                    elif cmd[0] is CserverCmd.INVALID_USERNAME:
                        msg = ("Sorry, name must contain only letters, numbers and underscore.",)
                    elif cmd[0] is CserverCmd.WELCOME_USER:
                        name = cmd[1]
                        msg = ("Welcome {0}!".format(name),)
                        self.state = CserverClientState.LOGGED_IN
                        self.username = name
                    elif cmd[0] is CserverCmd.MSG:
                        user, cmsg = (cmd[1], cmd[2])
                        msg = ("{0}: {1}".format(user, cmsg),)
                    elif cmd[0] is CserverCmd.PRIVATE:
                        targets = cmd[1]
                        msg = ("* you are now chatting privately: {0}".format(" ".join(targets)),)
                        self.targets = targets
                    elif cmd[0] is CserverCmd.PUBLIC:
                        msg = ("* you are now chatting publicly",)
                        self.targets = None
                    elif cmd[0] is CserverCmd.INVALID_PRIVATE:
                        msg = ("Sorry, user {0} is not available.".format(cmd[1]),)
                    elif cmd[0] is CserverCmd.SHOW_ROOMS:
                        room_names = cmd[1]
                        msg = ["Active rooms are:",]
                        for rn, ru in room_names:
                            msg.append("* {0} ({1})".format(rn, len(ru)))
                        msg.append("End of list.")
                    elif cmd[0] is CserverCmd.CREATE_ROOM:
                        user, room = (cmd[1], cmd[2])
                        msg = ("* user has created {0}: {1} (** this is you)".format(room, user),)
                    elif cmd[0] is CserverCmd.SEE_CREATE_ROOM:
                        user, room = (cmd[1], cmd[2])
                        msg = ("* user has created {0}: {1}".format(room, user),)
                    elif cmd[0] is CserverCmd.JOIN_ROOM:
                        user, room, room_users = (cmd[1], cmd[2], cmd[3])
                        msg = ["Entering room: {0}".format(room),]
                        for un in room_users:
                            if un == self.username:
                                msg.append("* {0} (** this is you)".format(un))
                                self.state = CserverClientState.IN_ROOM
                                self.roomname = room
                            else:
                                msg.append("* {0}".format(un))
                        msg.append("End of list.")
                    elif cmd[0] is CserverCmd.SEE_JOIN_ROOM:
                        user, room = (cmd[1], cmd[2])
                        msg = ("* new user joined {0}: {1}".format(room, user),)
                    elif cmd[0] is CserverCmd.LEAVE_ROOM:
                        user, room = (cmd[1], cmd[2])
                        msg = ("* user has left {0}: {1} (** this is you)".format(room, user),)
                        self.state = CserverClientState.LOGGED_IN
                        self.roomname = None
                        self.targets = None
                    elif cmd[0] is CserverCmd.SEE_LEAVE_ROOM:
                        user, room = (cmd[1], cmd[2])
                        msg = ("* user has left {0}: {1}".format(room, user),)
                    elif cmd[0] is CserverCmd.INVALID_ROOM:
                        msg = ("Sorry, room {0} is not available.".format(cmd[1]),)
                    elif cmd[0] is CserverCmd.INVALID_ROOMNAME:
                        msg = ("Sorry, room name must contain only letters, numbers and underscore.",)
                    elif cmd[0] is CserverCmd.EXISTING_ROOM:
                        msg = ("Sorry, room {0} already exists.".format(cmd[1]),)
                    elif cmd[0] is CserverCmd.NOT_IN_ROOM:
                        msg = ("Sorry, you are not in a room. Use /join to enter a room",)
                    elif cmd[0] is CserverCmd.QUIT:
                        msg = ("BYE",)
                    elif cmd[0] is CserverCmd.INVALID_CMD:
                        msg = ("Sorry, you have entered an unknown command",)

                    if msg is not None:
                        for m in msg:
                            if not self._send(str(m + '\n')):
                                return

                    if cmd[0] is CserverCmd.QUIT:
                        self.username = None
                        self.roomname = None
                        return
                finally:
                    self.outbound_queue.task_done()
                
        finally:
            logging.info("exiting outbound_handler thread")
            self._inbound_queue.put((CserverCmd.MSG, self, "/quit"))
            self._csocket.shutdown(socket.SHUT_RDWR)
            self._csocket.close()

    def inbound_handler(self):
        """Parse and handle all incoming client traffic."""
        logging.info("starting client inbound_handler of socket {0}".format(self._csocket.getpeername()))

        try:
            while (True):
                msg = self._recv()
                if msg is None:
                    return
                logging.debug("inbound message {0}".format(msg))
                self._inbound_queue.put((CserverCmd.MSG, self, msg))
        except OSError as ex:
            if self.username is not None or self.roomname is not None:
                logging.error("unexpected inbound_handler termination: {0}".format(ex))
        finally:
            logging.info("exiting inbound_handler thread")

    def _send(self, msg):
        """Send a message to the client.

        Args:

        msg (str): the message

        Return True if message sent successfully, False if failure

        """
        try:
            bmsg = msg.encode()
            while (len(bmsg) > 0):
                sent = self._csocket.send(bmsg)
                if sent == 0:
                    logging.error('failed to send message, client disconnected')
                    return False
                bmsg = bmsg[sent:]
        except Exception as ex:
            logging.error('failed to send message to client {0}: {1}'.format(self._csocket.getpeername(), ex))
            return False
        return True

    def _recv(self):
        """Receive a message from the client.

        Return message (str) or None if failure

        """
        RECV_SIZE = 1024
        try:
            while (True):
                m = self._csocket.recv(RECV_SIZE)
                if not m:
                    logging.error('failed to recv message, client disconnected')
                    return None
                self._recv_str = self._recv_str + m.decode()
                if self._recv_str.find('\n') >= 0:
                    lines = self._recv_str.splitlines()
                    self._recv_str = '\n'.join(lines[1:])
                    return lines[0]
        except Exception as ex:
            logging.error('failed to recv message to client {0}: {1}'.format(self._csocket.getpeername(), ex))
            return False
        return True

