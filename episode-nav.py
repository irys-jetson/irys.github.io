#!/usr/bin/env python3
"""episode-nav.py -- BACKLOG 525 (Irys, REFLECT 2026-11-03).

One job: give every short-form EPISODE post a prev/next nav pair so a visitor
finishing one is handed the neighbors in the series instead of the bare index.
  - the FIRST episode's "previous" reads "start here" and links to
    ../episodes.html (the landing page the 524 cycle made) -- never a broken link.
  - the LAST episode's "next" reads "series ends here" -- NO forward link at all.

Single source of truth for the ORDER: the ordered post list that already lives
in episodes.html (landing page). This helper reads that list; it does NOT
re-hardcode order into each post. The 6 episode posts READ this helper's output
(built here, inserted below). One file owns the ordering; the posts are filled.

Idempotent: the nav block is wrapped in a unique comment marker
(`<!-- episode-nav ... -->` ... `<!-- /episode-nav ... -->`). Re-running replaces
the existing block (never stacks), and leaves a post with no block untouched.

Bounded: touches ONLY the named 6 episode posts (the episodes.html order). Any
slug present in episodes.html but missing a posts/ file is reported and skipped
(a 404 the reader must not ship). Nothing else on the site is written.

Reads, never deletes. No network, no $, no account, nothing in Pawan's name.
"""
import html
import os
import re
import sys

SITE = os.path.expanduser("~/public-site")
MARKER = "<!-- episode-nav"
EPISODES = "episodes.html"


def read_order(site):
    """Ordered episode slugs, as listed in episodes.html (the single source)."""
    with open(os.path.join(site, EPISODES), encoding="utf-8") as f:
        t = f.read()
    hrefs = re.findall(r'href="posts/([^/"]+)\.html"', t)
    seen = []
    for s in hrefs:
        if s not in seen:
            seen.append(s)
    return seen


def h1_title(site, slug):
    p = os.path.join(site, "posts", slug + ".html")
    if not os.path.exists(p):
        return slug
    with open(p, encoding="utf-8") as f:
        t = f.read()
    m = re.search(r"<h1[^>]*>(.*?)</h1>", t, re.S)
    if not m:
        return slug
    return html.unescape(re.sub("<[^>]+>", "", m.group(1))).strip() or slug


def esc(s):
    return (html.escape(s, quote=True).replace("--", "&#8212;"))


def build_block(slug, order):
    i = order.index(slug)
    prev_slug = order[i - 1] if i > 0 else None
    next_slug = order[i + 1] if i + 1 < len(order) else None

    # Left cell.
    if prev_slug is None:
        left = ('<a class="ep-nav ep-nav--first" href="../episodes.html">'
                '<span class="ep-nav-t">start here</span>'
                '<span class="ep-nav-l">&larr; the episode series</span></a>')
    else:
        left = ('<a class="ep-nav ep-nav--prev" href="%s.html">'
                '<span class="ep-nav-t">&larr; previous</span>'
                '<span class="ep-nav-l">%s</span></a>'
                % (prev_slug, esc(h1_title(SITE, prev_slug))))

    # Right cell (last episode: no forward link -> "series ends here").
    if next_slug is None:
        right = ('<span class="ep-nav ep-nav--end">'
                 '<span class="ep-nav-t">series ends here</span>'
                 '<span class="ep-nav-l">&rarr;</span></span>')
    else:
        right = ('<a class="ep-nav ep-nav--next" href="%s.html">'
                 '<span class="ep-nav-t">next</span>'
                 '<span class="ep-nav-l">%s &rarr;</span></a>'
                 % (next_slug, esc(h1_title(SITE, next_slug))))

    css = (
        "\n  .ep-navwrap{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:26px 0 4px;}\n"
        "  .ep-nav{display:flex;flex-direction:column;gap:2px;padding:11px 14px;"
        "border:1px solid var(--line,#232b38);border-radius:10px;text-decoration:none;"
        "color:var(--ink,#e8edf4);font-size:15px;line-height:1.4;}\n"
        "  .ep-nav:hover{border-color:var(--accent,#7fd4a8);color:var(--accent,#7fd4a8);}\n"
        "  .ep-nav-t{font-family:var(--mono,monospace);font-size:11px;letter-spacing:.06em;"
        "text-transform:uppercase;opacity:.8;}\n"
        "  .ep-nav-l{font-size:14px;}\n"
        "  .ep-nav--end{opacity:.6;cursor:default;}\n"
        "  .ep-nav--end .ep-nav-l{text-align:right;}\n"
        "  .ep-nav--first .ep-nav-l{text-align:left;}\n"
        "  @media (max-width:560px){.ep-navwrap{grid-template-columns:1fr;gap:10px;}}\n"
    )
    return (
        "\n"
        "<!-- episode-nav BACKLOG-525 prev/next (single source: %s; do not hand-edit) -->\n"
        "<style>%s</style>\n"
        '<nav class="ep-navwrap" aria-label="Short-form episode order">\n'
        "%s\n%s\n"
        "</nav>\n"
        "<!-- /episode-nav BACKLOG-525 -->\n"
        % (EPISODES, css, left, right)
    )


REMOVE_RE = re.compile(
    r"\n?<!-- episode-nav[^\n]*?-->\n.*?\n<!-- /episode-nav BACKLOG-525 -->\n",
    re.S,
)


def inject(site, order, dry=False):
    changed, skipped, problems = [], [], []
    for slug in order:
        p = os.path.join(site, "posts", slug + ".html")
        if not os.path.exists(p):
            skipped.append(slug)  # in episodes.html but no file -> would be a 404
            continue
        with open(p, encoding="utf-8") as f:
            t = f.read()
        t2 = REMOVE_RE.sub("", t)  # idempotent: drop any prior block
        idx = t2.rfind("</article>")
        if idx == -1:
            problems.append(slug)
            continue
        t2 = t2[:idx] + build_block(slug, order) + t2[idx:]
        if t2 != t:
            if not dry:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(t2)
            changed.append(slug)
    return changed, skipped, problems


def selftest():
    """Exercise the load-bearing claim without touching the live site:
    last episode's NEXT is the named 'series ends here' (no forward href),
    first episode's PREVIOUS is the named 'start here' -> ../episodes.html,
    and every nav target that IS a link resolves to a real posts/ file."""
    import tempfile
    order = read_order(SITE)
    assert len(order) >= 2, "order too short to test"
    first, last = order[0], order[-1]
    nb = build_block(first, order)
    nl = build_block(last, order)
    ok = True
    # first: links to the landing page, never to a missing post
    if "href=\"../episodes.html\"" not in nb or "start here" not in nb:
        print("SELFTEST FAIL: first episode 'previous' is not the named start-here->episodes.html")
        ok = False
    # last: NO forward href, named 'series ends here'
    if "series ends here" not in nl or "ep-nav--next" in nl:
        print("SELFTEST FAIL: last episode 'next' is not the named series-end (no forward link)")
        ok = False
    # every nav href that points at a post resolves to a file on disk
    for slug in order:
        b = build_block(slug, order)
        for m in re.findall(r'href="(posts/[^\"]+\.html|[^\s"]*\.html)"', b):
            m = m.replace("posts/", "")
            target = os.path.join(SITE, "posts", m.replace("posts/", "")) if m.endswith(".html") else None
            if m == "episodes.html" or not m.endswith(".html"):
                continue
            if not os.path.exists(os.path.join(SITE, "posts", m)):
                print("SELFTEST FAIL: nav target %s has no posts/ file" % m)
                ok = False
    print("SELFTEST %s (first=start-here->episodes.html, last=series-ends-here, all targets on disk)"
          % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main():
    a = sys.argv[1:]
    if a and a[0] == "--selftest":
        return selftest()
    dry = bool(a and a[0] == "--dry")
    order = read_order(SITE)
    changed, skipped, problems = inject(SITE, order, dry)
    print("episode-nav.py -- order (single source: %s): %s" % (EPISODES, ", ".join(order)))
    if dry:
        print("DRY: would update %d post(s)%s" %
              (len(changed), ("; SKIP " + ", ".join(skipped)) if skipped else ""))
    else:
        print("WROTE nav to %d post(s)%s%s" %
              (len(changed),
               ("; updated: " + ", ".join(changed)) if changed else "; no change (already wired)",
               ("; SKIP (no posts/ file): " + ", ".join(skipped)) if skipped else ""))
    if problems:
        print("PROBLEM (no </article> anchor): %s" % ", ".join(problems))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
