import logging


class AccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) != 5 or not isinstance(args[2], str):
            return True

        path = args[2]
        if path.split("?", 1)[0] == "/api/v1/health" and args[4] == 200:
            return False

        for prefix in ("/api/v1/download/", "/download/"):
            if path.startswith(prefix):
                record.args = (args[0], args[1], f"{prefix}[redacted]", args[3], args[4])
                break
        return True
