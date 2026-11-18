"""The error every layer raises; the API turns it into {ok: false, error: {code, message, ...}}."""


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, **data):
        super().__init__(message)
        self.status = status
        self.code = code
        self.data = data

    def to_json(self) -> dict:
        return {"ok": False, "error": {"code": self.code, "message": str(self), **self.data}}


def invalid(message: str, code: str = "invalid", **data) -> ApiError:
    return ApiError(422, code, message, **data)


def not_found(what: str, ident) -> ApiError:
    return ApiError(404, "not_found", f"no {what} {ident}", what=what, id=str(ident))


def conflict(code: str, message: str, **data) -> ApiError:
    return ApiError(409, code, message, **data)
