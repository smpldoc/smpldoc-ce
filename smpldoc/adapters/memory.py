"""In-memory adapters: for tests and local trials. Nothing is persisted."""
import hashlib
from collections import deque
from itertools import count

from smpldoc.domain.bundle import check_store_names
from smpldoc.domain.models import Inbound


class MemoryBlob:
    def __init__(self):
        self._data = {}

    def put(self, company_id, data):
        key = hashlib.sha256(data).hexdigest()
        self._data[(company_id, key)] = bytes(data)
        return key

    def get(self, company_id, key):
        try:
            return self._data[(company_id, key)]
        except KeyError:
            raise KeyError(key) from None


class MemoryBundleStore:
    """Same rules as FileBundleStore, in memory, for tests and trials."""

    def __init__(self):
        self._bundles = {}

    def put(self, company, bundle_id, files):
        check_store_names(company, bundle_id, files)
        self._bundles[(company, bundle_id)] = {path: bytes(data) for path, data in files.items()}

    def get(self, company, bundle_id):
        try:
            return dict(self._bundles[(company, bundle_id)])
        except KeyError:
            raise KeyError(bundle_id) from None

    def list_ids(self, company):
        return sorted(i for c, i in self._bundles if c == company)


class MemoryMailIn:
    def __init__(self):
        self._queue, self.inflight, self._raw, self._n = deque(), {}, {}, count(1)

    def deliver(self, raw, sender, recipient, verdict):
        i = f"mem{next(self._n)}"
        self._raw[i] = bytes(raw)
        self._queue.append(Inbound(i, i, sender, recipient, verdict, len(raw)))

    def poll(self, limit):
        out = []
        while self._queue and len(out) < limit:
            m = self._queue.popleft()
            self.inflight[m.receipt] = m
            out.append(m)
        return out

    def fetch(self, message):
        return self._raw[message.id]

    def ack(self, message):
        self.inflight.pop(message.receipt, None)
        self._raw.pop(message.id, None)

    def nack(self, message):
        m = self.inflight.pop(message.receipt, None)
        if m is not None:
            self._queue.appendleft(m)


class MemoryMailOut:
    """Records what would be sent. `fail_times` makes the next sends fail, as a transient or a permanent error."""

    def __init__(self):
        self.sent, self.fail_times, self.permanent, self._n = [], 0, False, count(1)

    def send(self, mail):
        from smpldoc.domain.errors import SendError

        if self.fail_times > 0:
            self.fail_times -= 1
            raise SendError("simulated failure", permanent=self.permanent)
        self.sent.append(mail)
        return f"<mem{next(self._n)}@memory.invalid>"
