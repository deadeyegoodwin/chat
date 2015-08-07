#
# Copyright 2015 David Goodwin. All rights reserved.
#

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

    # If the configuration file doesn't exist create it with empty
    # content
    if not os.path.exists(args.config):
        with shelve.open(args.config) as db:
            db['rooms'] = { 'public' }

    # Map of all the clients that have logged in users, indexed by the
    # name of the user.
    user_clients = { }

    # A single queue is used by all clients to communicate inbound
    # activity
    inbound_queue = queue.Queue()
 
    # Spawn a thread to wait for connections from new clients.
    conn_thread = Thread(target=_connection_handler, args=(args, inbound_queue))
    conn_thread.daemon = True
    conn_thread.start()

    # Main control loop... wait for new connections or other client
    # requests and handle them
    with shelve.open(args.config, writeback=True) as db:
        # Users currently in each room. Map indexed by room name
        # pointing to a set of usernames
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
                        # If the client is new then the message is a
                        # username. Make sure it is valid.
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
                            # client is logged in... decode the
                            # message to see if it is a command
                            # (e.g. /rooms) or a regular chat message
                            msg_kind, msg_payload = msgs.decode_msg(cmd[2])
                            # handle /rooms and /quit command
                            if msg_kind is CserverMsgKind.ROOMS_CMD:
                                client.outbound_queue.put((CserverCmd.SHOW_ROOMS, _get_room_list(room_users)))
                            elif msg_kind is CserverMsgKind.QUIT_CMD:
                                if client.username in user_clients:
                                    del user_clients[client.username]
                                client.outbound_queue.put((CserverCmd.QUIT,))
                            # handle /create
                            elif msg_kind is CserverMsgKind.CREATE_ROOM_CMD:
                                room = msg_payload
                                if room in room_users:
                                    client.outbound_queue.put((CserverCmd.EXISTING_ROOM, room))
                                elif not _roomname_re.match(room):
                                    client.outbound_queue.put((CserverCmd.INVALID_ROOMNAME,))
                                else:
                                    db['rooms'].add(room)
                                    room_users[room] = set()
                                    client.outbound_queue.put((CserverCmd.CREATE_ROOM, client.username, room))
                                    for cc in user_clients.values():
                                        if cc != client and cc.state is not CserverClientState.NEW:
                                            cc.outbound_queue.put((CserverCmd.SEE_CREATE_ROOM, client.username, room))
                            # handle /private and /public
                            elif msg_kind is CserverMsgKind.PRIVATE_CMD:
                                if client.state is not CserverClientState.IN_ROOM:
                                    client.outbound_queue.put((CserverCmd.NOT_IN_ROOM,))
                                else:
                                    targets = msg_payload
                                    if len(targets) > 0:
                                        for t in targets:
                                            if t not in room_users[client.roomname]:
                                                client.outbound_queue.put((CserverCmd.INVALID_PRIVATE, t))
                                                break
                                        else:
                                            client.outbound_queue.put((CserverCmd.PRIVATE, targets))
                            elif msg_kind is CserverMsgKind.PUBLIC_CMD:
                                if client.state is not CserverClientState.IN_ROOM:
                                    client.outbound_queue.put((CserverCmd.NOT_IN_ROOM,))
                                else:
                                    client.outbound_queue.put((CserverCmd.PUBLIC,))
                            # handle /join, if user is already in a
                            # room then leave it first
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
                            # handle /leave, can only leave if already
                            # in a room
                            elif msg_kind is CserverMsgKind.LEAVE_CMD:
                                if client.state is not CserverClientState.IN_ROOM:
                                    client.outbound_queue.put((CserverCmd.NOT_IN_ROOM,))
                                else:
                                    room_users[client.roomname].remove(client.username)
                                    client.outbound_queue.put((CserverCmd.LEAVE_ROOM, client.username, client.roomname))
                                    for cc in user_clients.values():
                                        if cc != client and cc.state is CserverClientState.IN_ROOM and cc.roomname == client.roomname:
                                            cc.outbound_queue.put((CserverCmd.SEE_LEAVE_ROOM, client.username, client.roomname))
                            # handle a normal chat request...
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
                                
                    else:
                        logger.error("unexpected command: {0}".format(cmd))
                finally:
                    inbound_queue.task_done()
        except KeyboardInterrupt as ex:
            logging.info('Server killed, exiting...')
            # send quit to all clients to give them a chance to exit gracefully
            for cc in user_clients.values():
                cc.outbound_queue.put((CserverCmd.QUIT,))
        
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
    """Handler for new client connections."""
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
