"""A tiny SMTP server on loopback for tests (the standard library no longer ships one)."""
import socketserver
import threading
from email import message_from_bytes


class FakeSmtp:
    def __init__(self, rcpt_reply="250 OK"):
        self.messages, self.commands, self.rcpt_reply = [], [], rcpt_reply
        smtp = self

        class H(socketserver.StreamRequestHandler):
            def handle(self):
                w = lambda s: (self.wfile.write(s.encode() + b"\r\n"), self.wfile.flush())
                w("220 fake ESMTP")
                sender, rcpts = "", []
                while True:
                    line = self.rfile.readline().decode(errors="replace").rstrip("\r\n")
                    if not line:
                        return
                    smtp.commands.append(line.split(" ")[0].upper())
                    cmd = line.upper()
                    if cmd.startswith("EHLO") or cmd.startswith("HELO"):
                        w("250-fake"), w("250 8BITMIME")
                    elif cmd.startswith("MAIL FROM"):
                        sender = line[10:].strip(), w("250 OK")
                    elif cmd.startswith("RCPT TO"):
                        if smtp.rcpt_reply.startswith("250"):
                            rcpts.append(line[8:].strip())
                        w(smtp.rcpt_reply)
                    elif cmd == "DATA":
                        w("354 go")
                        data = b""
                        while not data.endswith(b"\r\n.\r\n"):
                            chunk = self.rfile.readline()
                            if not chunk:
                                return
                            data += chunk
                        smtp.messages.append((sender[0] if sender else "", list(rcpts), message_from_bytes(data[:-5])))
                        w("250 queued")
                    elif cmd == "QUIT":
                        w("221 bye")
                        return
                    else:
                        w("250 OK")

        class S(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self.server = S(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
