import html
from typing import Annotated

from pydantic import BeforeValidator, HttpUrl


def unescape_url(url: HttpUrl) -> HttpUrl:
    return HttpUrl(html.unescape(str(url)))


UnescapedUrl = Annotated[HttpUrl, BeforeValidator(unescape_url)]
