#
# Copyright 2015 David Goodwin. All rights reserved.
#
# A simple chat server. The design goals of this server are
# robustness, scalability and extensibility. 
#
# One possible implementation would use a single thread along with
# select/poll and non-blocking sockets. Often such implementations
# overlook the need to handle partial socket sends and recvs, and
# doing so correctly can significantly complicate the solution.
#
# Instead, to provide robust socket send and recv behavior and to
# increase scalability this implementation uses multiple threads. Each
# connected chat client is managed by a corresponding CserverClient
# instance. Each instance maintains 2 threads, one to handle incoming
# socket traffic and one to handle outgoing traffic. The dedicated
# threads allow robust send/recv handling without complicated the main
# server thread.  
#
# The main server thread (in cserver.main) handles, in a serial
# manner, all client requests without needed to directly interact with
# the communication sockets. A well defined communication protocol
# exists between the client instance and the server thread to all easy
# extension of server functionality by the addition of new server
# commands and features.
#
# The server implements these minimum required features:
# - Chat user login
# - /rooms command to list all available rooms
# - /join command to join a room
# - /leave command to leave a room
# - /quit command to quit the chat session
#
# The server implements these additional features:
# - /create <roomname> command to create a new room
# - /private <user0> <user1> ... command to target subsequent chat
#   messages to a subset of the users currently in the room
# - /public command to target subsequent chat messages to all users in
#   the room
# - Persistent chat server state. Server state currently persists
#   rooms across server invocations but is extensible to handle future
#   possible features such are persistent user name, passwords, room
#   properties, etc.
#
# All minimum and additional features have appropriate error checking
# and reporting.

import logging
import msgs
import os
import queue
import re
import shelve
import socket
import sys
from threading import Thread
from msgs import CserverCmd
from msgs import CserverMsgKind
from oparse import CserverOptionParser
from client import CserverClient
from client import CserverClientState

_username_re = re.compile('\w*$')
_roomname_re = re.compile('\w*$')

def main(argv=None):
    """The main entry point for the chat server.

    argv - command-line arguments
    """
    # Parse command-line arguments
    parser = CserverOptionParser()
    args = parser.parse(argv)

    # Configure logging
    logging.basicConfig(format='%(asctime)s %(message)s', level=args.log_level)

    logging.info('Log level: {0}'.format(args.log_level))
    logging.info('Server addr: {0}:{1}'.format(args.hostname, args.port))
    logging.info('Server config: {0}'.format(args.config))

    # If the configuration file doesn't exist create the default chat
    # server with a single 'public' room
    if not os.path.exists(args.config):
        with shelve.open(args.config) as db:
            db['rooms'] = { 'public' }

    # Map of all the clients that have logged in users, indexed by the
    # name of the user (username -> CserverClient).
    user_clients = { }

    # A single queue is used by all clients to communicate inbound
    # activity
    inbound_queue = queue.Queue()
 
    # Spawn a thread to wait for connections from new clients. As each
    # new client connects a CserverClient object is created to manage
    # that client.
    conn_thread = Thread(target=_connection_handler, args=(args, inbound_queue))
    conn_thread.daemon = True
    conn_thread.start()

    # Main control loop... wait for new connections or other client
    # requests and handle them
    with shelve.open(args.config, writeback=True) as db:
        # Users currently in each room. (roomname -> set of usernames)
        room_users = { }
        for r in db['rooms']:
            room_users[r] = set()

        try:
            while (True):
                cmd = inbound_queue.get()
                logging.debug("server command {0}".format(cmd))
                try:
                    # For a new connection, display the banner and
                    # then request a login. Otherwise interpret the
                    # message in the current client state and respond
                    # appropriately.
                    if cmd[0] is CserverCmd.NEW_CLIENT:
                        client = cmd[1]
                        client.outbound_queue.put((CserverCmd.BANNER, args.banner))
                        client.outbound_queue.put((CserverCmd.LOGIN,))
                    elif cmd[0] is CserverCmd.MSG:
                        client = cmd[1]
                        # If the client is new then the message is
                        # interpreted as the login username. If it a
                        # valid username welcome the user and record
                        # that the user is represented by the
                        # appropriate CserverClient instance.
                        if client.state is CserverClientState.NEW:
                            username = cmd[2]
                            if username in user_clients:
                                client.outbound_queue.put((CserverCmd.EXISTING_USER,))
                                client.outbound_queue.put((CserverCmd.LOGIN,))
                            elif not _username_re.match(username):
                                client.outbound_queue.put((CserverCmd.INVALID_USERNAME,))
                                client.outbound_queue.put((CserverCmd.LOGIN,))
                            else:
                                user_clients[username] = client
                                client.outbound_queue.put((CserverCmd.WELCOME_USER, username))
                        else:
                            # User is already logged in so decode the
                            # message... it will either be a command
                            # or a chat message. For a command update
                            # the appropriate server state and send a
                            # command to the client(s) to perform the
                            # necessary actions required for that
                            # command.
                            msg_kind, msg_payload = msgs.decode_msg(cmd[2])
                            # /rooms
                            if msg_kind is CserverMsgKind.ROOMS_CMD:
                                client.outbound_queue.put((CserverCmd.SHOW_ROOMS, _get_room_list(room_users)))
                            # /create
                            elif msg_kind is CserverMsgKind.CREATE_ROOM_CMD:
                                room = msg_payload
                                if room in room_users:
                                    client.outbound_queue.put((CserverCmd.EXISTING_ROOM, room))
                                elif not _roomname_re.match(room):
                                    client.outbound_queue.put((CserverCmd.INVALID_ROOMNAME,))
                                else:
                                    db['rooms'].add(room)
                                    room_users[room] = set()
                                    # inform all logged-in users of the new room
                                    client.outbound_queue.put((CserverCmd.CREATE_ROOM, client.username, room))
                                    for cc in user_clients.values():
                                        if cc != client and cc.state is not CserverClientState.NEW:
                                            cc.outbound_queue.put((CserverCmd.SEE_CREATE_ROOM, client.username, room))
                            # /private
                            elif msg_kind is CserverMsgKind.PRIVATE_CMD:
                                if client.state is not CserverClientState.IN_ROOM:
                                    client.outbound_queue.put((CserverCmd.NOT_IN_ROOM,))
                                else:
                                    # All specified usernames must be in the room
                                    targets = msg_payload
                                    if len(targets) > 0:
                                        for t in targets:
                                            if t not in room_users[client.roomname]:
                                                client.outbound_queue.put((CserverCmd.INVALID_PRIVATE, t))
                                                break
                                        else:
                                            client.outbound_queue.put((CserverCmd.PRIVATE, targets))
                            # /public
                            elif msg_kind is CserverMsgKind.PUBLIC_CMD:
                                if client.state is not CserverClientState.IN_ROOM:
                                    client.outbound_queue.put((CserverCmd.NOT_IN_ROOM,))
                                else:
                                    client.outbound_queue.put((CserverCmd.PUBLIC,))
                            # /join, if user is already in a room then
                            # leave that room first before joining the
                            # new room
                            elif msg_kind is CserverMsgKind.JOIN_CMD:
                                room = msg_payload
                                if room not in room_users:
                                    client.outbound_queue.put((CserverCmd.INVALID_ROOM, room))
                                else:
                                    if client.state is CserverClientState.IN_ROOM:
                                        room_users[client.roomname].remove(client.username)
                                        client.outbound_queue.put((CserverCmd.LEAVE_ROOM, client.username, client.roomname))
                                        for cc in user_clients.values():
                                            if cc != client and cc.state is CserverClientState.IN_ROOM and cc.roomname == client.roomname:
                                                cc.outbound_queue.put((CserverCmd.SEE_LEAVE_ROOM, client.username, client.roomname))
                                    room_users[room].add(client.username)
                                    client.outbound_queue.put((CserverCmd.JOIN_ROOM, client.username, room, room_users[room]))
                                    for cc in user_clients.values():
                                        if cc != client and cc.state is CserverClientState.IN_ROOM and cc.roomname == room:
                                            cc.outbound_queue.put((CserverCmd.SEE_JOIN_ROOM, client.username, room))
                            # /leave
                            elif msg_kind is CserverMsgKind.LEAVE_CMD:
                                if client.state is not CserverClientState.IN_ROOM:
                                    client.outbound_queue.put((CserverCmd.NOT_IN_ROOM,))
                                else:
                                    room_users[client.roomname].remove(client.username)
                                    client.outbound_queue.put((CserverCmd.LEAVE_ROOM, client.username, client.roomname))
                                    for cc in user_clients.values():
                                        if cc != client and cc.state is CserverClientState.IN_ROOM and cc.roomname == client.roomname:
                                            cc.outbound_queue.put((CserverCmd.SEE_LEAVE_ROOM, client.username, client.roomname))
                            # /quit, leave room first if in a room
                            elif msg_kind is CserverMsgKind.QUIT_CMD:
                                if client.state is CserverClientState.IN_ROOM:
                                    room_users[client.roomname].remove(client.username)
                                    client.outbound_queue.put((CserverCmd.LEAVE_ROOM, client.username, client.roomname))
                                    for cc in user_clients.values():
                                        if cc != client and cc.state is CserverClientState.IN_ROOM and cc.roomname == client.roomname:
                                            cc.outbound_queue.put((CserverCmd.SEE_LEAVE_ROOM, client.username, client.roomname))
                                if client.username in user_clients:
                                    del user_clients[client.username]
                                client.outbound_queue.put((CserverCmd.QUIT,))
                            # chat message
                            elif msg_kind is CserverMsgKind.ALL_CHAT:
                                if client.state is not CserverClientState.IN_ROOM:
                                    client.outbound_queue.put((CserverCmd.NOT_IN_ROOM,))
                                else:
                                    if client.targets is None:
                                        target_clients = user_clients.values()
                                    else:
                                        target_clients = [ user_clients[t] for t in client.targets ]
                                        target_clients.append(client)
                                    for cc in target_clients:
                                        if cc.state is CserverClientState.IN_ROOM and cc.roomname == client.roomname:
                                            cc.outbound_queue.put((CserverCmd.MSG, client.username, msg_payload))
                            # unknown command...
                            elif msg_kind is CserverMsgKind.UNKNOWN_CMD:
                                client.outbound_queue.put((CserverCmd.INVALID_CMD,))
                                
                    else:
                        logger.error("unexpected command: {0}".format(cmd))
                finally:
                    inbound_queue.task_done()
        except KeyboardInterrupt as ex:
            logging.info('Server killed, exiting...')
            # send quit to all clients to give them a chance to exit gracefully
            for cc in user_clients.values():
                cc.outbound_queue.put((CserverCmd.QUIT,))
            # TODO should communicate with _connection_handler thread
            # to have it gracefully exit so that it can shutdown the
            # server socket. Currently just using a daemon thread
            # which causes the socket to not be gracefully closed but
            # there are better alternatives.
        
    return 0

def _get_room_list(room_users):
    """Return a list of tuples of (room name, room users), ordered by room
    name.

    Args:
    
    room_users (map room -> set of users names): the users currently
    in each room
    
    """
    rlist = list()
    for r in sorted(room_users):
        rlist.append((r, sorted(room_users[r])))
    return rlist

def _connection_handler(args, cmd_queue):
    """Handler for new client connections. For each new connection to the
    chat server a CserverClient instance is create to handle the
    client and a message is sent to the server thread to start the
    login for the client.

    Args:

    args: the cserver command-line arguments

    cmd_queue (queue.Queue): the queue to use to communicate to the
    server thread

    """
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind((args.hostname, args.port))
        s.listen(5)
        while (True):
            # Create the client for the connection...
            (csocket, addr) = s.accept()
            client = CserverClient(csocket, cmd_queue)
            # Send notification of the new client
            cmd_queue.put((CserverCmd.NEW_CLIENT, client))
    except OSError as ex:
        logging.error('Server failed: {0}'.format(ex))
    finally:
        if s:
            s.shutdown(socket.SHUT_RDWR)
            s.close()

# run the chat server
if __name__ == "__main__":
    sys.exit(main())
