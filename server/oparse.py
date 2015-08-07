#
# Copyright 2015 David Goodwin. All rights reserved.
#
import argparse
import logging

class CserverOptionParser:
    """Command-line parser for the char server."""

    def __init__(self):
        self._parser = argparse.ArgumentParser(description='Run a chat server.')
        self._parser.add_argument('--log-level', default='INFO', 
                                  choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'])
        self._parser.add_argument('--hostname', default='localhost', 
                                  help='Server hostname (default "localhost")')
        self._parser.add_argument('--port', type=int, default=19567, 
                                  help='Server port (default 19567)')
        self._parser.add_argument('--banner', default='Welcome to the XYZ chat server', 
                                  help='Banner to show to clients when they connect')
        self._parser.add_argument('config', 
                                  help='Filename for server configuration. Will be created if '
                                  'does not exist')
        
    def parse(self, argv):
        """Parse command-line options.

        argv - the command-line options (list of string)
        
        Return dictionary of the arguments.

        """
        return self._parser.parse_args(argv)
    
