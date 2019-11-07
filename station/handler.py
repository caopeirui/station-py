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
    Request Handler
    ~~~~~~~~~~~~~~~

    Handler for each connection
"""

import json
from socketserver import BaseRequestHandler
from typing import Optional

from dimp import ID, User
from dimp import Content
from dimp import InstantMessage, ReliableMessage
from dimsdk import NetMsgHead, NetMsg, CompletionHandler
from dimsdk import ReceiptCommand
from dimsdk import MessengerDelegate

from libs.common import Log, Messenger
from libs.server import Session

from .config import g_database, g_facebook, g_keystore, g_session_server
from .config import g_dispatcher, g_receptionist, g_monitor
from .config import current_station, station_name, local_servers


class RequestHandler(BaseRequestHandler, MessengerDelegate):

    def __init__(self, request, client_address, server):
        super().__init__(request=request, client_address=client_address, server=server)
        # messenger
        self.__messenger: Messenger = None

    def info(self, msg: str):
        Log.info('%s:\t%s' % (self.__class__.__name__, msg))

    def error(self, msg: str):
        Log.error('%s ERROR:\t%s' % (self.__class__.__name__, msg))

    @property
    def messenger(self) -> Messenger:
        if self.__messenger is None:
            m = Messenger()
            m.barrack = g_facebook
            m.key_cache = g_keystore
            m.delegate = self
            # set all local servers
            m.users = [current_station]
            for srv in local_servers:
                if srv in m.users:
                    continue
                m.users.append(srv)
            # set context
            m.context['database'] = g_database
            m.context['session_server'] = g_session_server
            m.context['receptionist'] = g_receptionist
            m.context['monitor'] = g_monitor
            m.context['request_handler'] = self
            m.context['client_address'] = self.client_address
            self.__messenger = m
        return self.__messenger

    @property
    def session(self) -> Optional[Session]:
        if self.__messenger is not None:
            return self.__messenger.session

    @session.setter
    def session(self, value: Session):
        if value is not None and self.__messenger is not None:
            self.__messenger.session = value

    @property
    def remote_user(self) -> Optional[User]:
        if self.__messenger is not None:
            return self.__messenger.remote_user

    @property
    def identifier(self) -> Optional[ID]:
        user = self.remote_user
        if user is not None:
            return user.identifier

    def current_session(self, identifier: ID=None) -> Optional[Session]:
        if identifier is None:
            # get current session
            return self.session
        if self.session is not None:
            # check whether the current session's identifier matched
            if self.session.identifier == identifier:
                # current session belongs to the same user
                return self.session
            else:
                # user switched, clear current session
                g_session_server.remove(session=self.session)
        # get new session with identifier
        self.session = g_session_server.new(identifier=identifier, client_address=self.client_address)
        return self.session

    def upload_data(self, data: bytes, msg: InstantMessage) -> Optional[str]:
        # upload encrypted file data
        pass

    def download_data(self, url: str, msg: InstantMessage) -> Optional[bytes]:
        # download encrypted file data
        pass

    def send_package(self, data: bytes, handler: CompletionHandler) -> bool:
        try:
            self.request.sendall(data)
            if handler is not None:
                handler.success()
            return True
        except IOError as error:
            self.error('failed to send data %s' % error)
            if handler is not None:
                handler.failed(error=error)
            return False

    def send(self, data: bytes) -> bool:
        try:
            self.request.sendall(data)
            return True
        except IOError as error:
            self.error('failed to send data %s' % error)
            return False

    def receive(self, buffer_size=1024) -> bytes:
        try:
            return self.request.recv(buffer_size)
        except IOError as error:
            self.error('failed to receive data %s' % error)

    def deliver_message(self, msg: ReliableMessage) -> Content:
        self.info('deliver message %s, %s' % (self.identifier, msg.envelope))
        g_dispatcher.deliver(msg)
        # response to sender
        response = ReceiptCommand.new(message='Message delivering')
        # extra info
        sender = msg.get('sender')
        receiver = msg.get('receiver')
        time = msg.get('time')
        group = msg.get('group')
        signature = msg.get('signature')
        # envelope
        response['sender'] = sender
        response['receiver'] = receiver
        if time is not None:
            response['time'] = time
        # group message?
        if group is not None and group != receiver:
            response['group'] = group
        # signature
        response['signature'] = signature
        return response

    def process_package(self, pack: bytes) -> Optional[bytes]:
        try:
            return self.messenger.received_package(data=pack)
        except Exception as error:
            self.error('parse message failed: %s' % error)

    #
    #
    #

    def setup(self):
        self.__messenger: Messenger = None
        self.info('%s: set up with %s' % (self, self.client_address))
        g_session_server.set_handler(client_address=self.client_address, request_handler=self)
        g_monitor.report(message='Client connected %s [%s]' % (self.client_address, station_name))

    def finish(self):
        if self.session is not None:
            nickname = g_facebook.nickname(identifier=self.identifier)
            self.info('disconnect from session %s, %s' % (self.identifier, self.client_address))
            g_monitor.report(message='User %s logged out %s %s' % (nickname, self.client_address, self.identifier))
            # clear current session
            g_session_server.remove(session=self.session)
        else:
            g_monitor.report(message='Client disconnected %s [%s]' % (self.client_address, station_name))
        g_session_server.clear_handler(client_address=self.client_address)
        self.info('finish (%s, %s)' % self.client_address)

    """
        DIM Request Handler
    """
    def handle(self):
        self.info('client connected (%s, %s)' % self.client_address)
        data = b''
        while current_station.running:
            # receive all data
            incomplete_length = len(data)
            while True:
                part = self.receive(1024)
                if part is None:
                    break
                data += part
                if len(part) < 1024:
                    break
            if len(data) == incomplete_length:
                self.info('no more data, exit (%d, %s)' % (incomplete_length, self.client_address))
                break

            # process package(s) one by one
            #    the received data packages maybe spliced,
            #    if the message data was wrap by other transfer protocol,
            #    use the right split char(s) to split it
            while len(data) > 0:

                # (Protocol A) Tencent mars?
                mars = False
                head = None
                try:
                    head = NetMsgHead(data=data)
                    if head.version == 200:
                        # OK, it seems be a mars package!
                        mars = True
                        self.push_message = self.push_mars_message
                except ValueError:
                    # self.error('not mars message pack: %s' % error)
                    pass
                # check mars head
                if mars:
                    self.info('@@@ msg via mars, len: %d+%d' % (head.head_length, head.body_length))
                    # check completion
                    pack_len = head.head_length + head.body_length
                    if pack_len > len(data):
                        # partially data, keep it for next loop
                        break
                    # cut out the first package from received data
                    pack = data[:pack_len]
                    data = data[pack_len:]
                    self.handle_mars_package(pack)
                    # mars OK
                    continue

                # (Protocol B) raw data with no wrap?
                if data.startswith(b'{"') and data.find(b'\0') < 0:
                    # OK, it seems be a raw package!
                    self.push_message = self.push_raw_message

                    # check completion
                    pos = data.find(b'\n')
                    if pos < 0:
                        # partially data, keep it for next loop
                        break
                    # cut out the first package from received data
                    pack = data[:pos+1]
                    data = data[pos+1:]
                    self.handle_raw_package(pack)
                    # raw data OK
                    continue

                if data == b'\n':
                    # NOOP: heartbeat package
                    pass
                # (Protocol ?)
                # TODO: split and unwrap data package(s)
                self.error('unknown protocol %s' % data)
                data = b''
                # raise AssertionError('unknown protocol')

    #
    #
    #

    def handle_mars_package(self, pack: bytes):
        pack = NetMsg(pack)
        head = pack.head
        self.info('@@@ processing package: cmd=%d, seq=%d' % (head.cmd, head.seq))
        if head.cmd == 3:
            # TODO: handle SEND_MSG request
            if head.body_length == 0:
                raise ValueError('messages not found')
            # maybe more than one message in a pack
            lines = pack.body.splitlines()
            body = b''
            for line in lines:
                if line.isspace():
                    self.info('ignore empty message')
                    continue
                response = self.process_package(line)
                if response:
                    body = body + response + b'\n'
            if body:
                data = NetMsg(cmd=head.cmd, seq=head.seq, body=body)
                # self.info('mars response %s' % data)
                self.send(data)
            else:
                # TODO: handle error message
                self.info('nothing to response')
        elif head.cmd == 6:
            # TODO: handle NOOP request
            self.info('receive NOOP package, response %s' % pack)
            self.send(pack)
        else:
            # TODO: handle Unknown request
            self.error('unknown package %s' % pack)
            self.send(pack)

    def handle_raw_package(self, pack: bytes):
        response = self.process_package(pack)
        if response:
            data = response + b'\n'
            self.send(data)
        else:
            self.error('process error %s' % pack)
            # self.send(pack)

    def push_mars_message(self, msg: ReliableMessage) -> bool:
        data = json.dumps(msg) + '\n'
        body = data.encode('utf-8')
        # kPushMessageCmdId = 10001
        # PUSH_DATA_TASK_ID = 0
        data = NetMsg(cmd=10001, seq=0, body=body)
        # self.info('pushing mars message %s' % data)
        return self.send(data)

    def push_raw_message(self, msg: ReliableMessage) -> bool:
        data = json.dumps(msg) + '\n'
        data = data.encode('utf-8')
        # self.info('pushing raw message %s' % data)
        return self.send(data)

    push_message = push_raw_message
