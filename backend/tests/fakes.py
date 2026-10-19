"""Small stand-ins for the dashboard connection and the narration session."""


class FakeUI:
    """Records every message the backend would send to the dashboard or extension."""

    def __init__(self):
        self.sent = []

    def __getattr__(self, name):
        if not name.startswith("send") and not name.startswith("broadcast"):
            raise AttributeError(name)

        async def record(session_id, *args, **kwargs):
            self.sent.append((name, args, kwargs))

        return record

    def names(self):
        return [n for n, _, _ in self.sent]


class FakeLiveSession:
    def __init__(self):
        self.spoken = []

    async def send_client_content(self, turns):
        self.spoken.append(turns.parts[0].text)
