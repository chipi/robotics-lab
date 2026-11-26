"""What the library raises: a code and a message, never a status. The caller that owns a transport maps the code (RFC-0030 section 4.1)."""


class PlanError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def invalid(message: str, code: str = "invalid") -> PlanError:
    return PlanError(code, message)
