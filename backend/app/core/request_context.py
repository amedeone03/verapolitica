from contextvars import ContextVar


request_id_var: ContextVar[str | None] = ContextVar(
    "verapolitica_request_id", default=None
)


def current_request_id() -> str | None:
    return request_id_var.get()
