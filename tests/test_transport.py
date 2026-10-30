"""Transport regressions; fixtures never constitute live market evidence."""
import io
import http.client
import http.server
import json
import ssl
import threading
import urllib.request
import unittest
from email.message import Message
from unittest.mock import patch

import research_519 as src


class Response(io.BytesIO):
    status = 200
    code = 200
    reason = 'OK'
    msg = 'OK'
    headers = Message()

    def info(self):
        return self.headers

    def getcode(self):
        return self.code


class Connection:
    debuglevel = 0
    _http_vsn = 11
    _http_vsn_str = 'HTTP/1.1'
    instances = []
    status = 200

    def __init__(self, host, **kwargs):
        self.host = host
        self.kwargs = kwargs
        self.sock = None
        self.calls = []
        self.closed = False
        self.__class__.instances.append(self)

    def set_debuglevel(self, value):
        pass

    def request(self, method, target, body=None, headers=None, **kwargs):
        self.calls.append((method, target, headers))

    def getresponse(self):
        response = Response(json.dumps({'serverTime': 1793382451761}).encode())
        response.status = response.code = self.status
        return response

    def close(self):
        self.closed = True


class PersistentTransportTests(unittest.TestCase):
    def setUp(self):
        Connection.instances = []
        Connection.status = 200

    def test_two_requests_reuse_one_tls_connection(self):
        with patch('urllib.request.getproxies', return_value={}), patch(
            'http.client.HTTPSConnection', Connection
        ):
            provider = src.HttpProvider(pace=0)
            first = provider.get('/api/v3/time')
            second = provider.get('/api/v3/time')
        self.assertEqual(first, second)
        self.assertEqual(provider.requests, 2)
        self.assertEqual(len(Connection.instances), 1)
        self.assertEqual(len(Connection.instances[0].calls), 2)
        context = Connection.instances[0].kwargs['context']
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_proxy_route_keeps_existing_urllib_transport(self):
        sentinel = object()
        with patch('urllib.request.getproxies', return_value={'https':'http://proxy.invalid:8080'}), patch(
            'urllib.request.proxy_bypass', return_value=False
        ), patch('urllib.request.build_opener', return_value=sentinel) as build:
            provider = src.HttpProvider(pace=0)
        self.assertIs(provider.opener, sentinel)
        build.assert_called_once()

    def test_http_blocks_never_redirect_or_retry(self):
        for status in (301, 418, 429, 503):
            with self.subTest(status=status), patch('urllib.request.getproxies', return_value={}), patch(
                'http.client.HTTPSConnection', Connection
            ):
                Connection.instances = []
                Connection.status = status
                provider = src.HttpProvider(pace=0)
                with self.assertRaisesRegex(src.FatalSourceError, f'HTTP_{status}_FAIL_CLOSED'):
                    provider.get('/api/v3/time')
                self.assertEqual(provider.requests, 1)
                self.assertEqual(len(Connection.instances), 1)
                self.assertEqual(len(Connection.instances[0].calls), 1)

    def test_wire_failure_closes_without_retry(self):
        with patch('urllib.request.getproxies', return_value={}), patch(
            'http.client.HTTPSConnection', Connection
        ), patch.object(Connection, 'request', side_effect=http.client.RemoteDisconnected('closed')) as request:
            provider = src.HttpProvider(pace=0)
            with self.assertRaisesRegex(src.FatalSourceError, 'SOURCE_UNAVAILABLE_RemoteDisconnected'):
                provider.get('/api/v3/time')
            self.assertEqual(request.call_count, 1)
            self.assertTrue(Connection.instances[0].closed)

    def test_transport_cannot_target_another_host_or_trade_path(self):
        targets = ('https://evil.invalid/api/v3/time', src.BASE_URL+'/api/v3/order',
                   'http://data-api.binance.vision/api/v3/time',
                   'https://user:pass@data-api.binance.vision/api/v3/time')
        with patch('urllib.request.getproxies', return_value={}), patch(
            'http.client.HTTPSConnection', Connection
        ):
            provider = src.HttpProvider(pace=0)
            for url in targets:
                with self.subTest(url=url), self.assertRaisesRegex(src.FatalSourceError, 'DISALLOWED_TRANSPORT_TARGET'):
                    provider.opener.open(urllib.request.Request(url), timeout=1)
        self.assertEqual(Connection.instances, [])

    def test_real_local_socket_is_reused(self):
        # Real HTTP framing/socket test; TLS trust is asserted separately above.
        peers = []
        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def do_GET(self):
                peers.append(self.client_address)
                payload = b'{"serverTime":1793382451761}'
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            def log_message(self, *args):
                pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        class LocalConnection(http.client.HTTPConnection):
            def __init__(self, host, timeout, context):
                super().__init__('127.0.0.1', server.server_port, timeout=timeout)
        try:
            with patch('urllib.request.getproxies', return_value={}), patch(
                'http.client.HTTPSConnection', LocalConnection
            ):
                provider = src.HttpProvider(pace=0)
                provider.get('/api/v3/time')
                provider.get('/api/v3/time')
                provider.opener.connection.close()
            self.assertEqual(len(peers), 2)
            self.assertEqual(peers[0], peers[1])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
