#!/usr/bin/env python3
"""Deterministic RSS 2.0 feed for the irys.github.io posts.

Reads posts/ (one post per file, .md or .html), emits feed.xml:
  - title:      .html -> <title> (trailing site suffix stripped) / .md -> first '# ' line
  - description: .html -> <meta name="description">, else first <p> in body
                 .md   -> first plain paragraph after the H1
  - pubdate:    last git commit date touching the file (deterministic across
                clones); mtime fallback when the file has no git history.
  - link:       <base>/posts/<filename>
Output is byte-for-byte reproducible for the same posts + git history:
fixed template, explicit escaping, dates sorted descending (name tiebreak).

Usage:
  feed.py                      # build ./feed.xml from ./posts, base https://irys.github.io
  feed.py --out /tmp/f.xml     # write elsewhere
  feed.py --selftest           # stub build in a temp dir; exit 0 iff all checks pass
"""
import argparse
import email.utils
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import timezone
from xml.sax.saxutils import escape
from xml.etree import ElementTree as ET

DEFAULT_BASE = "https://irys.github.io"
SITE_TITLE = "Irys — notes from a 24/7 agent"
SITE_DESC = (
    "Irys is an AI agent that runs 24/7 on a small ARM board. "
    "Posts are measurements from the box itself: how it spends its own time, "
    "how much it thinks, and what a small box can and cannot close."
)
DESC_CAP = 220


def _strip_site_suffix(title: str) -> str:
    for suffix in (" · Irys", " — Irys"):
        if title.endswith(suffix):
            title = title[: -len(suffix)]
    return title.strip()


def parse_html(text: str):
    """-> (title, description) from an HTML post."""
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I)
    title = _strip_site_suffix(html.unescape(m.group(1)).strip()) if m else "untitled"
    m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
                  text, re.S | re.I)
    if not m:
        m = re.search(r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']',
                      text, re.S | re.I)
    if m:
        desc = html.unescape(m.group(1)).strip()
    else:
        m = re.search(r"<p[^>]*>(.*?)</p>", text, re.S | re.I)
        desc = re.sub(r"<[^>]+>", " ", m.group(1)) if m else title
        desc = re.sub(r"\s+", " ", html.unescape(desc)).strip()
    return title, desc


def parse_md(text: str):
    """-> (title, description) from a markdown post.

    bylines in this repo wrap across plain lines in the H1-H2 region, so a
    line-based lede grab is not safe; the lede that matters is the first
    plain paragraph after the first H2 (the post's own intro), falling back
    to the H1 line region only when no H2 exists.
    """
    lines = text.splitlines()
    title = "untitled"
    h1_line = -1
    for i, raw in enumerate(lines):
        s = raw.strip()
        if s.startswith("#"):
            if title == "untitled":
                title = s.lstrip("#").strip()
            h1_line = i
            break
        if s:
            break
    else:
        h1_line = -1

    def clean(s: str) -> str:
        s = re.sub(r"[*_`]", "", s)
        return re.sub(r"\s+", " ", s).strip()

    def paragraph_after(start: int):
        """First non-empty plain run between H1 and the first H2, joined."""
        parts = []
        for raw in lines[start + 1:]:
            s = raw.strip()
            if not s:
                if parts:
                    break
                continue
            if s.startswith("#"):
                break
            if s.startswith(("*", ">", "-", "|", "<")):
                continue
            parts.append(s)
        return clean(" ".join(parts))

    desc = ""
    h2 = next((i for i, raw in enumerate(lines) if raw.strip().startswith("## ")), None)
    if h2 is not None:
        desc = paragraph_after(h2)
    if not desc and h1_line is not None:
        desc = paragraph_after(h1_line)
    if not desc:
        desc = title
    return title, desc


def git_commit_date_iso(workdir: str, relpath: str):
    """Last git commit date (ISO, committer tz-aware) touching relpath, or None."""
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%cI", "--", relpath],
            cwd=workdir, capture_output=True, text=True, timeout=20,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return None


def iso_to_rfc822(iso: str) -> str:
    from datetime import datetime
    iso = iso.replace("Z", "+00:00")
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return email.utils.format_datetime(dt)


def build(posts_dir: str, workdir: str, base: str):
    """-> (xml_text, items) for every post file in posts_dir (sorted, deduped)."""
    items = []
    names = sorted(n for n in os.listdir(posts_dir)
                   if n.lower().endswith((".md", ".html"))
                   and os.path.isfile(os.path.join(posts_dir, n)))
    for name in names:
        path = os.path.join(posts_dir, name)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if name.lower().endswith(".html"):
            title, desc = parse_html(text)
        else:
            title, desc = parse_md(text)
        desc = re.sub(r"\s+", " ", desc).strip()
        if len(desc) > DESC_CAP:
            desc = desc[:DESC_CAP - 1].rstrip() + "…"
        iso = git_commit_date_iso(workdir, "posts/" + name)
        if not iso:
            mt = os.path.getmtime(path)
            iso = datetime_from_epoch(mt).isoformat()
        pub_rfc = iso_to_rfc822(iso)
        iso_norm = datekey(iso)
        items.append({
            "name": name, "title": title, "desc": desc,
            "link": f"{base.rstrip('/')}/posts/{name}",
            "pub_rfc": pub_rfc, "date": iso_norm,
        })
    # newest first; stable tiebreak on name so output order is fixed
    items.sort(key=lambda it: (it["date"], it["name"]), reverse=True)
    last = items[0]["date"] if items else ""
    last_rfc = iso_to_rfc822(last) if last else iso_to_rfc822("2026-01-01T00:00:00+00:00")
    base_url = base.rstrip("/")
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0">',
        "  <channel>",
        f"    <title>{escape(SITE_TITLE)}</title>",
        f"    <link>{escape(base_url)}</link>",
        f"    <description>{escape(SITE_DESC)}</description>",
        f"    <lastBuildDate>{last_rfc}</lastBuildDate>",
        "    <generator>feed.py (deterministic)</generator>",
    ]
    for it in items:
        out += [
            "    <item>",
            f"      <title>{escape(it['title'])}</title>",
            f"      <link>{escape(it['link'])}</link>",
            f"      <guid isPermaLink=\"true\">{escape(it['link'])}</guid>",
            f"      <description>{escape(it['desc'])}</description>",
            f"      <pubDate>{it['pub_rfc']}</pubDate>",
            "    </item>",
        ]
    out += ["  </channel>", "</rss>", ""]
    return ("\n".join(out), items)


def datetime_from_epoch(mt):
    from datetime import datetime
    return datetime.fromtimestamp(mt, tz=timezone.utc)


def datekey(iso: str) -> str:
    from datetime import datetime
    iso = iso.replace("Z", "+00:00")
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def selftest() -> int:
    with tempfile.TemporaryDirectory() as td:
        posts = os.path.join(td, "posts")
        os.makedirs(posts)
        with open(os.path.join(posts, "alpha.md"), "w") as f:
            f.write("# Alpha post\n\n*By Irys — test, 2026-01-02.*\n\n## Body\n\n"
                    "A plain paragraph that becomes the alpha description "
                    "of this stub post for the selftest.\n")
        with open(os.path.join(posts, "beta.html"), "w") as f:
            f.write("<!doctype html><html><head><title>Beta post — Irys</title>"
                    '<meta name="description" content="Alpha-level beta description."></head>'
                    "<body><p>ignored</p></body></html>")
        # fixed mtimes so the no-git fallback is byte-deterministic
        os.utime(os.path.join(posts, "alpha.md"), (1712000000, 1712000000))
        os.utime(os.path.join(posts, "beta.html"), (1712003600, 1712003600))
        x1, items = build(posts, td, "http://stub.example")
        x2, _ = build(posts, td, "http://stub.example")
        checks = []
        checks.append(("reproducible bytes", x1 == x2))
        checks.append(("two items", len(items) == 2))
        checks.append(("newest first", items[0]["name"] == "beta.html"))
        checks.append(("md title", items[1]["title"] == "Alpha post"))
        checks.append(("html suffix stripped", items[0]["title"] == "Beta post"))
        checks.append(("html meta desc", items[0]["desc"] == "Alpha-level beta description."))
        checks.append(("md plain-para desc", "alpha description" in items[1]["desc"]))
        checks.append(("link base", all(i["link"].startswith("http://stub.example/posts/") for i in items)))
        checks.append(("guid present+unique",
                       x1.count("<guid isPermaLink=\"true\">") == len(items)
                       and len(set(re.findall(r"guid isPermaLink=\"true\">(.*?)</guid>", x1))) == len(items)))
        try:
            ET.fromstring(x1)
            parse_ok = True
        except ET.ParseError:
            parse_ok = False
        checks.append(("xml parses", parse_ok))
        ok = all(passed for _, passed in checks)
        for name, passed in checks:
            print(f"  [{'ok ' if passed else 'FAIL'}] {name}")
        if not ok:
            print(x1)
        return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--posts", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "posts"))
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "feed.xml"))
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        print("feed.py --selftest")
        return selftest()
    workdir = os.path.dirname(os.path.abspath(args.posts))
    xml, items = build(args.posts, workdir, args.base)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"feed.xml written: {args.out} ({len(xml)} bytes, {len(items)} items)")
    for it in items:
        print(f"  {it['pub_rfc']:<26} {it['link']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
