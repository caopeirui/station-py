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
    Command Processor for 'storage'
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    storage protocol: post/get contacts, private_key, ...
"""

from dimp import ID
from dimp import InstantMessage
from dimp import Content, TextContent
from dimp import Command
from dimsdk import ReceiptCommand, StorageCommand
from dimsdk import CommandProcessor

from ..database import Database


class StorageCommandProcessor(CommandProcessor):

    @property
    def database(self) -> Database:
        return self.get_context('database')

    def __get_contacts(self, sender: ID) -> Content:
        # query encrypted contacts, load it
        stored: Command = self.database.contacts_command(identifier=sender)
        # response
        if stored is not None:
            # response the stored contacts command directly
            return stored
        else:
            return TextContent.new(text='Sorry, contacts of %s not found.' % sender)

    def __put_contacts(self, cmd: StorageCommand, sender: ID) -> Content:
        # receive encrypted contacts, save it
        if self.database.save_contacts_command(cmd=cmd, sender=sender):
            return ReceiptCommand.new(message='Contacts of %s received!' % sender)
        else:
            return TextContent.new(text='Contacts not stored %s!' % cmd)

    def __process_contacts(self, cmd: StorageCommand, sender: ID) -> Content:
        if cmd.data is None and 'contacts' not in cmd:
            # query contacts, load it
            return self.__get_contacts(sender=sender)
        else:
            # upload contacts, save it
            return self.__put_contacts(cmd=cmd, sender=sender)

    #
    #   main
    #
    def process(self, content: Content, sender: ID, msg: InstantMessage) -> Content:
        assert isinstance(content, StorageCommand), 'command error: %s' % content
        title = content.title
        if title == StorageCommand.CONTACTS:
            return self.__process_contacts(cmd=content, sender=sender)
        # error
        return TextContent.new(text='Storage command (title: %s) not support yet!' % title)


# register
CommandProcessor.register(command=StorageCommand.STORAGE, processor_class=StorageCommandProcessor)
CommandProcessor.register(command=StorageCommand.CONTACTS, processor_class=StorageCommandProcessor)
CommandProcessor.register(command=StorageCommand.PRIVATE_KEY, processor_class=StorageCommandProcessor)
