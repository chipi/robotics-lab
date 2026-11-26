"""The duck's local controller `rules@1` (RFC-0025 section 3.7): the follower's command, unchanged. The local layer's rules are the
navigator's guards, which stay where they are; this is the default, and a profile that names no controller gets it."""


class Rules:
    name = "rules"
    version = 1
    ident = "rules@1"

    def __init__(self, profile=None):
        self.bind(profile)

    def bind(self, profile) -> None:
        self.profile = profile

    def reset(self) -> None:
        pass

    def command(self, requested, ranges, body, applied):
        return requested

    def describe(self) -> dict:
        return {"name": self.name, "version": self.version, "ident": self.ident}
