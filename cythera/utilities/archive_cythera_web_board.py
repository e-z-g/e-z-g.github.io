#!/usr/bin/env python3
"""Archive Cythera Web Board topics as plain text intended for LLM ingestion.

Install: python3 -m pip install requests beautifulsoup4
Test:    python3 archive_cythera_web_board.py --topic 2041 --verbose
All:     python3 archive_cythera_web_board.py --verbose
Combine: python3 archive_cythera_web_board.py --combine

Output is one .txt file per topic (plus an optional single concatenated file).
No HTML, no CSS, no avatars, no emoji images: just post text with a short
metadata header per post.
"""
from __future__ import annotations

import argparse
import logging
import mimetypes
import re
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = "http://forums.cytheraguides.com"
BOARD = BASE + "/category/6/cythera-web-board"
OUT = Path("cythera-web-board-archive")
DELAY_SECONDS = 2.0
TIMEOUT = (10, 45)
MAX_TOPIC_PAGES = 500
MAX_BOARD_PAGES = 200
HEADERS = {
    "User-Agent": "CytheraBoardPersonalArchive/2.0 (polite archival downloader)",
    "Accept-Language": "en-GB,en;q=0.9",
}
# Forum furniture that carries no meaning in a text transcript.
EXCLUDED_IMAGE_PREFIXES = (
    BASE + "/plugins/",
    BASE + "/assets/uploads/profile/",
    BASE + "/assets/customicons/",
)
SKIP_TAGS = {"script", "style", "noscript", "button", "form", "svg", "select", "textarea"}
BLOCK_TAGS = {
    "p", "div", "section", "article", "header", "footer", "aside", "main",
    "h1", "h2", "h3", "h4", "h5", "h6", "figure", "figcaption", "dl", "dd", "dt",
}
log = logging.getLogger("cythera_archive")

session = requests.Session()
session.headers.update(HEADERS)
retry = Retry(total=4, connect=4, read=4, backoff_factor=2,
              status_forcelist=(429, 500, 502, 503, 504),
              allowed_methods=frozenset(("GET",)), raise_on_status=False)
session.mount("http://", HTTPAdapter(max_retries=retry))
session.mount("https://", HTTPAdapter(max_retries=retry))


# --------------------------------------------------------------------------
# DNS gate: never spend a request (or a 45s timeout) on a domain that is gone.
# --------------------------------------------------------------------------

class DeadDomain(Exception):
    """Raised when a URL's host does not resolve."""


_dns_cache: dict[str, bool] = {}
_dns_enabled = True


def host_resolves(host: str | None) -> bool:
    """True if `host` has a DNS record. Results are cached for the whole run."""
    if not host:
        return False
    if not _dns_enabled:
        return True
    host = host.lower()
    if host in _dns_cache:
        return _dns_cache[host]
    alive = False
    for attempt in (1, 2):  # one retry, so a blip is not read as a dead domain
        try:
            socket.getaddrinfo(host, None)
            alive = True
            break
        except socket.gaierror:
            if attempt == 1:
                time.sleep(0.5)
        except OSError:  # resolver unavailable, etc: assume alive, let HTTP decide
            alive = True
            break
    _dns_cache[host] = alive
    log.debug("  DNS %s -> %s", host, "ok" if alive else "does not resolve")
    if not alive:
        print(f"  domain no longer resolves, ignoring: {host}")
    return alive


def url_is_live(url: str) -> bool:
    """True if `url` is an http(s) URL whose host still resolves."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    return host_resolves(parsed.hostname)


def get(url: str) -> requests.Response:
    if not url_is_live(url):
        raise DeadDomain(url)
    log.debug("GET %s", url)
    time.sleep(DELAY_SECONDS)
    response = session.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    log.debug("  -> HTTP %s, %s bytes", response.status_code, len(response.content))
    return response


def get_soup(url: str) -> BeautifulSoup:
    return BeautifulSoup(get(url).text, "html.parser")


# --------------------------------------------------------------------------
# Board crawl
# --------------------------------------------------------------------------

def canonical_topic_url(url: str) -> str | None:
    match = re.match(r"^/topic/(\d+)(?:/|$)", urlparse(url).path)
    return f"{BASE}/topic/{match.group(1)}" if match else None


def topic_links_from(soup: BeautifulSoup, page_url: str) -> set[str]:
    return {topic for a in soup.select('a[href*="/topic/"]')
            if (topic := canonical_topic_url(urljoin(page_url, a.get("href", ""))))}


def board_topic_urls() -> list[str]:
    """Walk the category's numbered pages until a page yields no new topics."""
    topics: set[str] = set()
    for page in range(1, MAX_BOARD_PAGES + 1):
        url = BOARD if page == 1 else f"{BOARD}?page={page}"
        print("BOARD", url)
        try:
            soup = get_soup(url)
        except (requests.RequestException, DeadDomain) as exc:
            print(f"  board page failed; stopping board crawl: {exc}")
            break
        found = topic_links_from(soup, url)
        new = found - topics
        print(f"  {len(found)} topic links ({len(new)} new)")
        if not new:
            # Either the last page, or the server ignored ?page= and re-served page 1.
            break
        topics |= new
    return sorted(topics, key=lambda u: int(re.search(r"/topic/(\d+)", u).group(1)))


# --------------------------------------------------------------------------
# Topic pagination
#
# The old code built page URLs as /topic/ID/SLUG/OFFSET?page=N but called the
# builder with the wrong arity, and looked for the next offset with a regex that
# assumed no slug segment (^/topic/\d+/(\d+)), so it never matched a real
# NodeBB link like /topic/2041/some-slug/41 and every topic stopped after page 1.
#
# Now: take the slug from the canonical link, page by first-post offset, and
# derive the next offset from the posts actually returned (data-index when
# NodeBB provides it). Stop when a page repeats or adds no new post IDs, which
# also covers the server clamping an over-large offset to the last page.
# --------------------------------------------------------------------------

def select_posts(soup: BeautifulSoup) -> list[Tag]:
    for selector in ("[component='post']", ".post[data-pid]", "li[data-pid]", "article[data-pid]"):
        posts = soup.select(selector)
        if posts:
            return posts
    return []


def post_identity(post: Tag) -> str:
    return str(post.get("data-pid") or post.get("id") or post.get_text(" ", strip=True)[:200])


def topic_slug(soup: BeautifulSoup, topic_id: str) -> str | None:
    for selector, attribute in (('link[rel="canonical"]', "href"),
                                ('meta[property="og:url"]', "content")):
        element = soup.select_one(selector)
        value = element.get(attribute) if element else None
        if not value:
            continue
        match = re.match(rf"^/topic/{topic_id}/([^/?#]+)", urlparse(urljoin(BASE, value)).path)
        if match:
            return match.group(1)
    return None


def next_offset(posts: list[Tag], current_offset: int) -> int:
    """First-post offset of the following page (1-based, as NodeBB URLs use)."""
    indexes = [int(p["data-index"]) for p in posts
               if str(p.get("data-index", "")).lstrip("-").isdigit()]
    if indexes:
        return max(indexes) + 2  # data-index is 0-based, URL offset is 1-based
    return current_offset + len(posts)


def offset_url(topic_id: str, slug: str | None, offset: int) -> str:
    stem = f"{BASE}/topic/{topic_id}" + (f"/{slug}" if slug else "")
    return stem if offset <= 1 else f"{stem}/{offset}"


def topic_pages(topic_id: str, first_url: str, first_soup: BeautifulSoup):
    """Yield (page_url, new_posts) for every page of a topic."""
    slug = topic_slug(first_soup, topic_id)
    log.debug("  slug=%s", slug)
    soup, url, offset = first_soup, first_url, 1
    seen_signatures: set[tuple[str, ...]] = set()
    seen_pids: set[str] = set()

    for _ in range(MAX_TOPIC_PAGES):
        posts = select_posts(soup)
        if not posts:
            print("  no post containers found; stopping pagination")
            return
        signature = tuple(post_identity(p) for p in posts)
        if signature in seen_signatures:
            print("  server re-served a page already seen; reached final page")
            return
        seen_signatures.add(signature)
        fresh = [p for p in posts if post_identity(p) not in seen_pids]
        if not fresh:
            print("  no new posts on this page; reached final page")
            return
        seen_pids.update(post_identity(p) for p in fresh)
        yield url, fresh

        offset = next_offset(posts, offset)
        url = offset_url(topic_id, slug, offset)
        log.debug("  next offset=%d -> %s", offset, url)
        print("  FETCH NEXT", url)
        try:
            soup = get_soup(url)
        except (requests.RequestException, DeadDomain) as exc:
            print(f"  next page failed; stopping this topic: {exc}")
            return
    print("  hit page cap; stopping this topic")


# --------------------------------------------------------------------------
# HTML -> plain text
# --------------------------------------------------------------------------

class RenderContext:
    def __init__(self, page_url: str, image_dir: Path | None, counter: list[int]):
        self.page_url = page_url
        self.image_dir = image_dir
        self.counter = counter


def _tidy(text: str) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _children(node: Tag, ctx: RenderContext) -> str:
    return "".join(_render(child, ctx) for child in node.children)


def _render_link(node: Tag, ctx: RenderContext) -> str:
    text = _children(node, ctx).strip()
    href = (node.get("href") or "").strip()
    if not href or href.startswith("#"):
        return text
    absolute = urljoin(ctx.page_url, href)
    if absolute.startswith("mailto:"):
        return text or absolute
    if not url_is_live(absolute):
        return text  # dead domain: keep what was written, drop the URL
    if not text:
        return absolute
    if text.rstrip("/") == absolute.rstrip("/"):
        return absolute
    return f"{text} <{absolute}>"


def _download_image(url: str, ctx: RenderContext) -> str | None:
    if ctx.image_dir is None:
        return None
    try:
        response = get(url)
    except (requests.RequestException, DeadDomain) as exc:
        print(f"  image unavailable: {url} ({exc})")
        return None
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0]
    extension = mimetypes.guess_extension(content_type) or Path(urlparse(url).path).suffix or ".bin"
    ctx.counter[0] += 1
    filename = f"image-{ctx.counter[0]:04d}{extension.lower()}"
    (ctx.image_dir / filename).write_bytes(response.content)
    log.debug("  saved image %s", filename)
    return f"images/{filename}"


def _render_image(node: Tag, ctx: RenderContext) -> str:
    absolute = urljoin(ctx.page_url, (node.get("src") or "").strip())
    alt = (node.get("alt") or "").strip()
    if not absolute or absolute.startswith(EXCLUDED_IMAGE_PREFIXES):
        return ""  # avatars, emoji, plugin icons
    if not url_is_live(absolute):
        return f"[image: {alt}]" if alt else ""
    saved = _download_image(absolute, ctx)
    target = saved or absolute
    return f"[image: {alt} {target}]" if alt else f"[image: {target}]"


def _render_list(node: Tag, ctx: RenderContext) -> str:
    ordered = node.name.lower() == "ol"
    items = []
    for number, li in enumerate(node.find_all("li", recursive=False), 1):
        inner = _tidy(_children(li, ctx))
        if not inner:
            continue
        marker = f"{number}. " if ordered else "- "
        lines = inner.splitlines()
        items.append(marker + lines[0] + "".join("\n  " + line for line in lines[1:]))
    return "\n\n" + "\n".join(items) + "\n\n" if items else ""


def _render_table(node: Tag, ctx: RenderContext) -> str:
    rows = []
    for tr in node.find_all("tr"):
        cells = [_tidy(_children(cell, ctx)).replace("\n", " ")
                 for cell in tr.find_all(["td", "th"], recursive=False)]
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n\n" + "\n".join(rows) + "\n\n" if rows else ""


def _render(node, ctx: RenderContext) -> str:
    if isinstance(node, NavigableString):
        return re.sub(r"\s+", " ", str(node))
    if not isinstance(node, Tag):
        return ""
    name = node.name.lower()
    if name in SKIP_TAGS:
        return ""
    if name == "br":
        return "\n"
    if name == "hr":
        return "\n\n"
    if name == "img":
        return _render_image(node, ctx)
    if name == "a":
        return _render_link(node, ctx)
    if name == "pre":
        code = node.get_text().strip("\n")
        return "\n\n```\n" + code + "\n```\n\n" if code.strip() else ""
    if name == "code":
        inner = re.sub(r"\s+", " ", node.get_text()).strip()
        return f"`{inner}`" if inner else ""
    if name == "blockquote":
        inner = _tidy(_children(node, ctx))
        if not inner:
            return ""
        quoted = "\n".join(("> " + line).rstrip() for line in inner.splitlines())
        return "\n\n" + quoted + "\n\n"
    if name in ("ul", "ol"):
        return _render_list(node, ctx)
    if name == "li":  # stray <li> outside a list
        return "\n" + _tidy(_children(node, ctx))
    if name == "table":
        return _render_table(node, ctx)
    if name in BLOCK_TAGS:
        inner = _tidy(_children(node, ctx))
        return "\n\n" + inner + "\n\n" if inner else ""
    return _children(node, ctx)


def html_to_text(node: Tag, page_url: str, image_dir: Path | None, counter: list[int]) -> str:
    return _tidy(_children(node, RenderContext(page_url, image_dir, counter)))


# --------------------------------------------------------------------------
# Post extraction
# --------------------------------------------------------------------------

def post_author(post: Tag) -> str:
    for selector in ('[itemprop="author"] [itemprop="name"]',
                     '[component="post/header"] [itemprop="name"]',
                     '[itemprop="author"]',
                     '[component="user/name"]',
                     ".username",
                     'a[href^="/user/"]'):
        element = post.select_one(selector)
        if element:
            text = element.get_text(" ", strip=True)
            if text:
                return text
            href = element.get("href", "")
            if href.startswith("/user/"):
                return href.split("/user/", 1)[1].strip("/") or "unknown"
    return str(post.get("data-username") or "unknown")


def post_timestamp(post: Tag) -> str:
    element = post.select_one("time[datetime]")
    if element:
        return element["datetime"]
    for element in post.select("[data-timestamp]"):
        raw = str(element.get("data-timestamp", ""))
        if raw.isdigit():
            moment = datetime.fromtimestamp(int(raw) / 1000, tz=timezone.utc)
            return moment.strftime("%Y-%m-%d %H:%M UTC")
    element = post.select_one(".timeago[title], [component='post/timeago'][title]")
    if element:
        return element["title"]
    return "unknown date"


def post_content_node(post: Tag) -> Tag:
    working = BeautifulSoup(str(post), "html.parser")
    for tag in working.select(
        'script, style, noscript, button, form, .dropdown, .moderator-tools, '
        '[component="post/tools"], [component="post/header"], [component="post/footer"], '
        '.post-tools, .votes, .stats, nav'
    ):
        tag.decompose()
    for selector in ('[component="post/content"]', '[itemprop="text"]', ".post-content", ".content"):
        node = working.select_one(selector)
        if node:
            return node
    return working


def archive_topic(topic_number_or_url: str, save_images: bool) -> str | None:
    topic_url = (topic_number_or_url if topic_number_or_url.startswith("http")
                 else f"{BASE}/topic/{topic_number_or_url}")
    topic_id = re.search(r"/topic/(\d+)", topic_url).group(1)
    topic_dir = OUT / topic_id
    topic_dir.mkdir(parents=True, exist_ok=True)
    image_dir = None
    if save_images:
        image_dir = topic_dir / "images"
        image_dir.mkdir(exist_ok=True)

    print("TOPIC", topic_id, topic_url)
    try:
        first_soup = get_soup(topic_url)
    except (requests.RequestException, DeadDomain) as exc:
        print(f"  topic failed; skipping: {exc}")
        return None

    heading = first_soup.select_one("h1")
    title = heading.get_text(" ", strip=True) if heading else f"Topic {topic_id}"

    counter = [0]
    blocks, total = [], 0
    for page_url, posts in topic_pages(topic_id, topic_url, first_soup):
        print(f"  PAGE {page_url} ({len(posts)} new posts)")
        for post in posts:
            total += 1
            body = html_to_text(post_content_node(post), page_url, image_dir, counter)
            if not body:
                continue
            blocks.append(
                f"--- post {total} | {post_author(post)} | {post_timestamp(post)} "
                f"| pid {post.get('data-pid') or 'unknown'}\n{body}"
            )

    document = "\n".join([
        f"topic: {title}",
        f"source: {topic_url}",
        f"posts: {len(blocks)}",
        f"archived: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        "",
        "\n\n".join(blocks),
        "",
    ])
    output = topic_dir / f"topic-{topic_id}.txt"
    output.write_text(document, encoding="utf-8")
    print(f"  WROTE {output} ({len(blocks)} posts)")
    return document


def main() -> int:
    global _dns_enabled

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--topic", type=int, help="Archive one topic number only")
    parser.add_argument("--combine", action="store_true",
                        help="Also write every topic into a single all-topics.txt")
    parser.add_argument("--save-images", action="store_true",
                        help="Download post images (off by default: text-only output)")
    parser.add_argument("--skip-dns-check", action="store_true",
                        help="Do not pre-check that domains resolve")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show HTTP requests, pagination, and DNS decisions")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(message)s")
    _dns_enabled = not args.skip_dns_check
    OUT.mkdir(exist_ok=True)

    if not url_is_live(BASE):
        print(f"{urlparse(BASE).hostname} does not resolve; nothing to archive.")
        return 1

    if args.topic is not None:
        return 0 if archive_topic(str(args.topic), args.save_images) else 1

    topics = board_topic_urls()
    (OUT / "topics.txt").write_text("\n".join(topics) + "\n", encoding="utf-8")
    print(f"Found {len(topics)} topic URLs")

    documents = []
    for topic in topics:
        document = archive_topic(topic, args.save_images)
        if document:
            documents.append(document)

    if args.combine and documents:
        combined = OUT / "all-topics.txt"
        combined.write_text("\n\n\n".join(documents), encoding="utf-8")
        print(f"WROTE {combined} ({len(documents)} topics)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
