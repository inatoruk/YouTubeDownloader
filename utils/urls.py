"""One validation and classification boundary for every URL entry point."""
from urllib.parse import urlsplit, urlunsplit, parse_qs, unquote

HOSTS = {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be', 'www.youtu.be'}


def classify_url(value: str) -> tuple[str, str]:
    value = value.strip()
    if '://' not in value:
        value = 'https://' + value
    try:
        parts = urlsplit(value)
        if (parts.scheme not in ('http', 'https') or parts.hostname not in HOSTS
                or parts.username is not None or parts.password is not None
                or parts.port is not None or any(c.isspace() for c in value)):
            raise ValueError('無効なYouTube URLです')
    except ValueError:
        raise ValueError('無効なYouTube URLです') from None
    path = unquote(parts.path)
    if not path or path == '/':
        raise ValueError('動画・プレイリスト・チャンネルのURLを入力してください')
    url = urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, parts.query, ''))
    query = parse_qs(parts.query)
    segments = path.strip('/').split('/')
    youtube = parts.hostname.endswith('youtube.com')
    if youtube and (segments[0].startswith('@') or segments[0] in ('channel', 'c', 'user')):
        return url, 'channel'
    list_id = query.get('list', [''])[0]
    if (youtube and path == '/playlist') or (list_id and not list_id.startswith(('RD', 'LL', 'FL', 'WL'))):
        if not list_id:
            raise ValueError('プレイリストIDがありません')
        return url, 'playlist'
    if parts.hostname.endswith('youtu.be') or (youtube and (path == '/watch' and query.get('v') or segments[0] in ('shorts', 'live', 'embed') and len(segments) > 1)):
        return url, 'video'
    raise ValueError('動画・プレイリスト・チャンネルのURLを入力してください')
