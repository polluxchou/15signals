#!/usr/bin/env python3
"""
本地 DeepSeek API 代理
解决浏览器 CORS 限制，将请求从 localhost 转发到 DeepSeek API
运行：python3 proxy.py
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request, urllib.error, ssl

PORT = 3458

class ProxyHandler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body   = self.rfile.read(length)
        auth   = self.headers.get('Authorization', '')

        req = urllib.request.Request(
            'https://api.deepseek.com/chat/completions',
            data=body,
            headers={
                'Content-Type':  'application/json',
                'Authorization': auth,
                'User-Agent':    'Mozilla/5.0'
            }
        )

        ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
                data = resp.read()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self._cors()
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            data = e.read()
            self.send_response(e.code)
            self.send_header('Content-Type', 'application/json')
            self._cors()
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            import json
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self._cors()
            self.end_headers()
            self.wfile.write(json.dumps({'error': str(e)}).encode())

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin',  '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')

    def log_message(self, fmt, *args):
        print(f'  {args[0]}  {args[1]}')

if __name__ == '__main__':
    server = HTTPServer(('localhost', PORT), ProxyHandler)
    print(f'\n✓ 代理已启动：http://localhost:{PORT}')
    print('  保持此窗口开启，然后刷新页面即可使用\n')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n代理已停止')
