from typing import Generator

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from upvote_monitor.constants import REQUESTS_TIMEOUT
from upvote_monitor.models.child import Children
from upvote_monitor.models.upvoted import UpvotedResponse

_RETRY_STATUS_CODES = (429, 500, 502, 503, 504)


def _build_session(user_agent: str, session_cookie: str) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=0.5,
        status_forcelist=_RETRY_STATUS_CODES,
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": user_agent,
            "Cookie": f"reddit_session={session_cookie}",
        }
    )
    return session


def upvoted_posts_generator(
    *,
    username: str,
    session_cookie: str,
    user_agent: str,
    page_size: int,
    page_limit: int,
) -> Generator[Children, None, None]:
    session = _build_session(user_agent, session_cookie)
    url = f"https://www.reddit.com/user/{username}/upvoted.json"

    after = None
    pages_fetched = 0

    while pages_fetched < page_limit:
        response = session.get(
            url,
            params={"limit": page_size, "after": after},
            timeout=REQUESTS_TIMEOUT,
        )
        response.raise_for_status()
        pages_fetched += 1

        response_parsed = UpvotedResponse(**response.json())
        yield from response_parsed.data.children

        after = response_parsed.data.after

        if not after:
            break


def validate_reddit_credentials(
    *,
    username: str,
    session_cookie: str,
    user_agent: str,
) -> None:
    session = _build_session(user_agent, session_cookie)
    response = session.get(
        f"https://www.reddit.com/user/{username}/upvoted.json",
        params={"limit": 1},
        timeout=REQUESTS_TIMEOUT,
    )
    response.raise_for_status()
    UpvotedResponse(**response.json())
