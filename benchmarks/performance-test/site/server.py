# Static server with a /poll endpoint that holds the connection 30s (simulates long-polling SPA)
import http.server, os, sys, time, threading
ROOT=os.path.dirname(os.path.abspath(__file__))
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self,*a,**k): super().__init__(*a,directory=ROOT,**k)
    def do_GET(self):
        if self.path.startswith('/poll'):
            time.sleep(30); self.send_response(204); self.end_headers(); return
        return super().do_GET()
    def log_message(self,*a): pass
http.server.ThreadingHTTPServer(('127.0.0.1',int(sys.argv[1]) if len(sys.argv)>1 else 8765),H).serve_forever()
