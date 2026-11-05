from itsdangerous import BadSignature, TimestampSigner

COOKIE_NAME = "hanbot_session"
MAX_AGE_SECONDS = 30 * 24 * 3600


def _signer(secret: str) -> TimestampSigner:
    return TimestampSigner(secret, salt="hanbot-session")


def issue_session_token(secret: str, username: str) -> str:
    return _signer(secret).sign(username).decode()


def read_session_token(secret: str, token: str) -> str | None:
    try:
        return _signer(secret).unsign(token, max_age=MAX_AGE_SECONDS).decode()
    except (BadSignature, UnicodeDecodeError):
        return None
