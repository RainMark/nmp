import io
import logging
from urllib.parse import quote

from nmp.log import TokenFilter


def test_sensitive_values_are_redacted_from_logs():
    token = 'secret token/value'
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    token_filter = TokenFilter()
    token_filter.set_token(token)
    handler.addFilter(token_filter)
    logger = logging.getLogger('tests.redaction')
    logger.addHandler(handler)
    logger.propagate = False
    logger.warning(f'plain={token} encoded={quote(token, safe="")}')
    logger.removeHandler(handler)

    output = stream.getvalue()
    assert token not in output
    assert quote(token, safe='') not in output
    assert output.count('[redacted]') == 2
