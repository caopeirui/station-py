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

import hashlib
import json
import struct
from socketserver import BaseRequestHandler
from typing import Optional

from dimp import User
from dimp import InstantMessage, ReliableMessage
from dimsdk import NetMsgHead, NetMsg, CompletionHandler
from dimsdk import MessengerDelegate

from libs.common import Log, base64_encode
from libs.server import Session
from libs.server import ServerMessenger
from libs.server import HandshakeDelegate

from .config import g_database, g_facebook, g_keystore, g_session_server
from .config import g_dispatcher, g_receptionist, g_monitor
from .config import current_station, station_name, chat_bot


class RequestHandler(BaseRequestHandler, MessengerDelegate, HandshakeDelegate):

    def __init__(self, request, client_address, server):
        super().__init__(request=request, client_address=client_address, server=server)
        # messenger
        self.__messenger: ServerMessenger = None
        # handlers with Protocol
        self.process_package = None
        self.push_data = None

    def info(self, msg: str):
        Log.info('%s >\t%s' % (self.__class__.__name__, msg))

    def error(self, msg: str):
        Log.error('%s >\t%s' % (self.__class__.__name__, msg))

    @property
    def chat_bots(self) -> list:
        bots = []
        # Tuling
        tuling = chat_bot('tuling')
        if tuling is not None:
            bots.append(tuling)
        # XiaoI
        xiaoi = chat_bot('xiaoi')
        if xiaoi is not None:
            bots.append(xiaoi)
        return bots

    @property
    def messenger(self) -> ServerMessenger:
        if self.__messenger is None:
            m = ServerMessenger()
            m.barrack = g_facebook
            m.key_cache = g_keystore
            m.dispatcher = g_dispatcher
            m.delegate = self
            # set context
            m.context['database'] = g_database
            m.context['session_server'] = g_session_server
            m.context['receptionist'] = g_receptionist
            m.context['bots'] = self.chat_bots
            m.context['handshake_delegate'] = self
            m.context['remote_address'] = self.client_address
            self.__messenger = m
        return self.__messenger

    @property
    def remote_user(self) -> Optional[User]:
        if self.__messenger is not None:
            return self.__messenger.remote_user

    #
    #
    #
    def setup(self):
        self.__messenger: ServerMessenger = None
        self.process_package = None
        self.push_data = None
        address = self.client_address
        self.info('set up with %s [%s]' % (address, station_name))
        g_session_server.set_handler(client_address=address, request_handler=self)
        g_monitor.report(message='Client connected %s [%s]' % (address, station_name))

    def finish(self):
        address = self.client_address
        user = self.remote_user
        if user is None:
            g_monitor.report(message='Client disconnected %s [%s]' % (address, station_name))
        else:
            nickname = g_facebook.nickname(identifier=user.identifier)
            session = g_session_server.get(identifier=user.identifier, client_address=address)
            if session is None:
                self.error('user %s not login yet %s %s' % (user, address, station_name))
            else:
                g_monitor.report(message='User %s logged out %s [%s]' % (nickname, address, station_name))
                # clear current session
                g_session_server.remove(session=session)
        # remove request handler fro session handler
        g_session_server.clear_handler(client_address=address)
        self.__messenger = None
        self.info('finish with %s %s' % (address, user))

    """
        DIM Request Handler
    """

    def handle(self):
        self.info('client connected (%s, %s)' % self.client_address)
        data = b''
        while current_station.running:
            # receive all data
            incomplete_length = len(data)
            data = self.receive()
            if len(data) == incomplete_length:
                self.info('no more data, exit (%d, %s)' % (incomplete_length, self.client_address))
                break

            # check protocol
            while self.process_package is None:
                # (Protocol A) Web socket?
                if data.find(b'Sec-WebSocket-Key') > 0:
                    self.process_package = self.process_ws_handshake
                    self.push_data = self.push_ws_data
                    break

                # (Protocol B) Tencent mars?
                try:
                    head = NetMsgHead(data=data)
                    if head.version == 200:
                        # OK, it seems be a mars package!
                        self.process_package = self.process_mars_package
                        self.push_data = self.push_mars_data
                        break
                except ValueError:
                    # self.error('not mars message pack: %s' % error)
                    pass

                # (Protocol C) raw data (JSON in line)?
                if data.startswith(b'{"') and data.find(b'\0') < 0:
                    self.process_package = self.process_raw_package
                    self.push_data = self.push_raw_data
                    break

                # unknown protocol
                data = b''
                # raise AssertionError('unknown protocol')
                break
            if self.process_package is None:
                continue

            # process package(s) one by one
            #    the received data packages maybe spliced,
            #    if the message data was wrap by other transfer protocol,
            #    use the right split char(s) to split it
            data = self.process_package(data)

    #
    #   Protocol: WebSocket
    #
    ws_magic = b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
    ws_prefix = b'HTTP/1.1 101 Switching Protocol\r\n' \
                b'Server: DIM-Station\r\n' \
                b'Upgrade: websocket\r\n' \
                b'Connection: Upgrade\r\n' \
                b'WebSocket-Protocol: dimchat\r\n' \
                b'Sec-WebSocket-Accept: '
    ws_suffix = b'\r\n\r\n'

    def process_ws_handshake(self, pack: bytes):
        pos1 = pack.find(b'Sec-WebSocket-Key:')
        pos1 += len('Sec-WebSocket-Key:')
        pos2 = pack.find(b'\r\n', pos1)
        key = pack[pos1:pos2].strip()
        sec = hashlib.sha1(key + self.ws_magic).digest()
        sec = base64_encode(sec)
        res = self.ws_prefix + bytes(sec, 'UTF-8') + self.ws_suffix
        self.send(res)
        self.process_package = self.process_ws_package
        return b''

    def process_ws_package(self, pack: bytes):
        msg_len = pack[1] & 127
        if msg_len == 126:
            mask = pack[4:8]
            content = pack[8:]
        elif msg_len == 127:
            mask = pack[10:14]
            content = pack[14:]
        else:
            mask = pack[2:6]
            content = pack[6:]
        data = ''
        for i, d in enumerate(content):
            data += chr(d ^ mask[i % 4])
        res = self.received_package(bytes(data, 'UTF-8'))
        self.push_ws_data(res)
        return b''

    def push_ws_data(self, body: bytes) -> bool:
        head = struct.pack('B', 129)
        msg_len = len(body)
        if msg_len < 126:
            head += struct.pack('B', msg_len)
        elif msg_len <= (2 ** 16 - 1):
            head += struct.pack('!BH', 126, msg_len)
        elif msg_len <= (2 ** 64 - 1):
            head += struct.pack('!BQ', 127, msg_len)
        else:
            raise ValueError('message is too long: %d' % msg_len)
        return self.send(head + body)

    #
    #   Protocol: Tencent mars
    #
    def process_mars_package(self, pack: bytes):
        mars = NetMsg(pack)
        head = mars.head
        # check completion
        mars_len = head.head_length + head.body_length
        pack_len = len(pack)
        if mars_len > pack_len:
            # partially data, keep it for next loop
            return pack
        # cut sticky packages
        remaining = pack[mars_len:]
        pack = pack[:mars_len]
        if head.cmd == 3:
            # TODO: handle SEND_MSG request
            if head.body_length == 0:
                raise ValueError('messages not found')
            body = self.received_package(mars.body)
            res = NetMsg(cmd=head.cmd, seq=head.seq, body=body)
        elif head.cmd == 6:
            # TODO: handle NOOP request
            self.info('receive NOOP package, cmd=%d, seq=%d, package: %s' % (head.cmd, head.seq, pack))
            res = pack
        else:
            # TODO: handle Unknown request
            self.error('receive unknown package, cmd=%d, seq=%d, package: %s' % (head.cmd, head.seq, pack))
            res = b''
        self.send(res)
        # return the remaining incomplete package
        return remaining

    def push_mars_data(self, body: bytes) -> bool:
        # kPushMessageCmdId = 10001
        # PUSH_DATA_TASK_ID = 0
        data = NetMsg(cmd=10001, seq=0, body=body)
        return self.send(data)

    #
    #   Protocol: raw data (JSON string)
    #
    def process_raw_package(self, pack: bytes):
        pack_len = len(pack)
        pos = 0
        # skip leading empty packages
        while pack[pos] == b'\n' or pack[pos] == b' ':
            pos += 1
        if pos == pack_len:
            # NOOP: heartbeat package
            self.info('respond <heartbeats>: %s' % pack)
            self.send(b'\n')
            return b''
        # check whether contain incomplete message
        pos = pack.rfind(b'\n')
        if pos < 0:
            return pack
        # maybe more than one message in a time
        res = self.received_package(pack[:pos])
        self.send(res)
        # return the remaining incomplete package
        return pack[pos+1:]

    def push_raw_data(self, body: bytes) -> bool:
        data = body + b'\n'
        return self.send(data=data)

    def push_message(self, msg: ReliableMessage) -> bool:
        data = json.dumps(msg)
        body = data.encode('utf-8')
        return self.push_data(body=body)

    #
    #   receive message(s)
    #
    def received_package(self, pack: bytes) -> Optional[bytes]:
        lines = pack.splitlines()
        body = b''
        for line in lines:
            line = line.strip()
            if len(line) == 0:
                self.info('ignore empty message')
                continue
            try:
                res = self.messenger.received_package(data=line)
                if res is None:
                    # station MUST respond something to client request
                    res = b''
                else:
                    res = res + b'\n'
            except Exception as error:
                self.error('parse message failed: %s' % error)
                # from dimsdk import TextContent
                # return TextContent.new(text='parse message failed: %s' % error)
                res = b''
            body = body + res
        # all responses in one package
        return body

    #
    #   Socket IO
    #
    def receive(self) -> bytes:
        data = b''
        while True:
            try:
                part = self.request.recv(1024)
            except IOError as error:
                self.error('failed to receive data %s' % error)
                part = None
            if part is None:
                break
            data += part
            if len(part) < 1024:
                break
        return data

    def send(self, data: bytes) -> bool:
        try:
            self.request.sendall(data)
            return True
        except IOError as error:
            self.error('failed to send data %s' % error)
            return False

    #
    #   MessengerDelegate
    #
    def send_package(self, data: bytes, handler: CompletionHandler) -> bool:
        if self.push_data(body=data):
            if handler is not None:
                handler.success()
            return True
        else:
            if handler is not None:
                error = IOError('MessengerDelegate error: failed to send data package')
                handler.failed(error=error)
            return False

    def upload_data(self, data: bytes, msg: InstantMessage) -> str:
        # upload encrypted file data
        pass

    def download_data(self, url: str, msg: InstantMessage) -> Optional[bytes]:
        # download encrypted file data
        pass

    #
    #   HandshakeDelegate
    #
    def handshake_accepted(self, session: Session):
        sender = session.identifier
        session_key = session.session_key
        client_address = session.client_address
        user = g_facebook.user(identifier=sender)
        self.messenger.remote_user = user
        self.info('handshake accepted %s %s %s, %s' % (user.name, client_address, sender, session_key))
        g_monitor.report(message='User %s logged in %s %s' % (user.name, client_address, sender))
        # add the new guest for checking offline messages
        g_receptionist.add_guest(identifier=sender)

    def handshake_success(self):
        # TODO: broadcast 'login'
        pass
