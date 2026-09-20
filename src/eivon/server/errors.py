"""Stable public errors independent of transport."""


class ServiceError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, details: object = None):
        super().__init__(message)
        self.code, self.message, self.status, self.details = code, message, status, details
