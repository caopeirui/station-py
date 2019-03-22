# -*- coding: utf-8 -*-
# ==============================================================================
# MIT License
#
# Copyright (c) 2019 Albert Moky
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# ==============================================================================

"""
    Station Receptionist
    ~~~~~~~~~~~~~~~~~~~~

    A message scanner for new guests who have just come in.
"""

from json import JSONDecodeError
from threading import Thread
from time import sleep

import dimp

from .database import Database
from .session import SessionServer


class Receptionist(Thread):

    def __init__(self):
        super().__init__()
        self.guests = []
        self.database: Database = None
        self.session_server: SessionServer = None
        self.station = None

    def add_guest(self, identifier: dimp.ID):
        self.guests.append(identifier)

    def any_guest(self) -> dimp.ID:
        identifier = self.guests.pop()
        if identifier:
            return dimp.ID(identifier)

    def request_handler(self, identifier: dimp.ID):
        return self.session_server.request_handler(identifier=identifier)

    def run(self):
        print('scanning session(s)...')
        while self.station.running:
            try:
                identifier = self.any_guest()
                if identifier:
                    handler = self.request_handler(identifier=identifier)
                    if handler:
                        # this guest is connected, scan messages for it
                        messages = self.database.load_messages(identifier)
                        if messages:
                            for msg in messages:
                                handler.push_message(msg)
            except IOError as error:
                print('session scanning IO error:', error)
            except JSONDecodeError as error:
                print('session scanning decode error:', error)
            except TypeError as error:
                print('session scanning type error:', error)
            except ValueError as error:
                print('session scanning value error:', error)
            finally:
                # sleep 1 second for next loop
                sleep(1.0)
        print('session scanner stopped!')
