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
    Command Process Units
    ~~~~~~~~~~~~~~~~~~~~~

    Processors for commands
"""

from typing import Optional

from dimp import ID
from dimp import Content, Command

from libs.common import Log, Facebook, Database
from libs.server import SessionServer


class CPU:

    def __init__(self, facebook: Facebook, database: Database, session_server: SessionServer):
        super().__init__()
        self.facebook = facebook
        self.database = database
        self.session_server = session_server
        # cache
        self.__processors = {}

    def info(self, msg: str):
        Log.info('%s:\t%s' % (self.__class__.__name__, msg))

    def error(self, msg: str):
        Log.error('%s ERROR:\t%s' % (self.__class__.__name__, msg))

    def process(self, cmd: Command, sender: ID) -> Optional[Content]:
        if type(self) != CPU:
            raise AssertionError('override me!')
        command = cmd.command
        # get processor from cache
        cpu = self.__processors.get(command)
        if cpu is None:
            # try to create new processor
            clazz = processor_classes.get(command)
            if clazz is None:
                self.error('command "%s" not supported yet!' % command)
                return None
            cpu = clazz()
            self.__processors[command] = cpu
        # process by subclass
        return cpu.process(cmd=cmd, sender=sender)


"""
    Commander Processor Classes Map
"""

processor_classes = {}