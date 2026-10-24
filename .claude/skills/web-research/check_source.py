"""Read-only robots.txt check. Usage: python check_source.py <url>
Makes one request (robots.txt) and never fetches the page itself."""
import sys
import urllib.error
import urllib.request
import urllib.robotparser
from urllib.parse import urlparse

UA = "trading-picker-research/0.1 (robots check; contact: project owner)"


def main(url):
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        sys.exit("Give a full URL such as https://example.com/path")
    robots = f"{p.scheme}://{p.netloc}/robots.txt"
    req = urllib.request.Request(robots, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            text = r.read(200000).decode("utf-8", "replace")
            print(f"robots.txt: HTTP {r.status} ({robots})")
    except urllib.error.HTTPError as e:
        print(f"robots.txt: HTTP {e.code} ({robots}) - not read")
        if e.code in (403, 429):
            print("Blocked. Stop and ask the user; do not work around it.")
        return
    except Exception as e:
        print(f"robots.txt: not read ({e})")
        return
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(text.splitlines())
    path = url
    print(f"Allowed for '*': {rp.can_fetch('*', path)}  ({p.path or '/'})")
    print(f"Allowed for our UA: {rp.can_fetch(UA, path)}")
    print(f"Crawl-delay: {rp.crawl_delay('*')}")
    print("--- first 20 lines ---")
    print("\n".join(text.splitlines()[:20]))
    print("Terms page is NOT checked by this script; read it yourself.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
