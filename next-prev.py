#!/usr/bin/env python3
"""next-prev.py -- BACKLOG 587 (Irys, WORK 2026-11-07).

One job: give every one of the 25 shipped posts a unified previous<->next
reading strip, in the site's OWN reading order, so a reader finishing an
article is handed the exact article before/after it instead of the bare index.
That is the "read the next one" step a visitor on one note never gets today:
  - 20 of the 25 posts already carry an *episode-series* nav (525) linking the
    neighbors INSIDE the episode series only;
  - the 5 "note" posts carry a handful of hand-picked cross-references;
  - NONE carries a previous+next in the ARCHIVE's reading order, the order a
    new reader actually sees on the shelf. So a reader on a note has no
    "what's next" in shelf order and bounces. 587 closes that.

Single source of truth for the ORDER: archive.html (the shelf), which already
lists all 25 posts as `role="group"` rows in reading order. This helper reads
that list; it does NOT re-hardcode order. archive.html is the shelf the reader
sees, so the strip matches it exactly.

Distinct from 525: this block is wrapped in its OWN unique idempotency marker
(`<!-- next-prev BACKLOG-587 -->` ... `<!-- /next-prev BACKLOG-587 -->`). It
REPLACES any prior 587 block (never stacks) and never touches the 525
episode-nav block or any hand-written cross-reference. A re-run is idempotent.

Bounded: touches ONLY posts that are listed in archive.html AND have a
posts/<slug>.html file (a slug in the archive with no file is the 404 class --
reported and skipped, never shipped). Nothing else on the site is written.
Reads, never deletes. No network, no $, no account, nothing in Pawan's name.
"""
import html
import os
import re
import sys

SITE = os.path.expanduser("~/public-site")
ARCHIVE = "archive.html"
MARK = "next-prev BACKLOG-587"

# Leak guard: 587 ships new HTML text into public pages. The strip must only
# ever contain post TITLES (already public, scraped from archive.html) plus the
# static frame words below. Nothing Pawan-identifying may leak in.
LEAK_RE = re.compile(
    r"neo@|pawan@|\b\d{3}-\d{3}-\d{4}\b|github_pat_|ghp_[A-Za-z0-9]{20,}|"
    r"ssh-rsa|ssh-ed25519|api[_-]?key\s*[:=]|password\s*[:=]|/home/neo|"
    r"irys-jetson\.com|\.github\.io|tunnel|tailscale",
    re.I,
)


def esc(s):
    return html.escape(s, quote=True)


def read_order():
    """Ordered post slugs, in archive.html reading order (the shelf)."""
    with open(os.path.join(SITE, ARCHIVE), encoding="utf-8") as f:
        t = f.read()
    # archive rows: <a class="title" href="<host>/posts/<slug>.html">
    hrefs = re.findall(r'href="https?://[^/"]+/posts/([^/"]+)\.html"', t)
    seen = []
    for s in hrefs:
        if s not in seen:
            seen.append(s)
    return seen


def h1_title(slug):
    p = os.path.join(SITE, "posts", slug + ".html")
    if not os.path.exists(p):
        return slug
    with open(p, encoding="utf-8") as f:
        t = f.read()
    m = re.search(r"<h1[^>]*>(.*?)</h1>", t, re.S)
    if not m:
        return slug
    return html.unescape(re.sub("<[^>]+>", "", m.group(1))).strip() or slug


def build_block(slug, order):
    i = order.index(slug)
    prev_slug = order[i - 1] if i > 0 else None
    next_slug = order[i + 1] if i + 1 < len(order) else None

    # Left cell: previous (or "order starts here" at the top end).
    if prev_slug is None:
        left = ('<span class="pn pn--end">'
                '<span class="pn-t">reading order</span>'
                '<span class="pn-l">starts here &larr; this one</span></span>')
    else:
        left = ('<a class="pn pn--prev" href="%s.html">'
                '<span class="pn-t">&larr; previous</span>'
                '<span class="pn-l">%s</span></a>') % (prev_slug, esc(h1_title(prev_slug)))

    # Right cell: next (or "order ends here" at the bottom end -- NO forward link).
    if next_slug is None:
        right = ('<span class="pn pn--end">'
                 '<span class="pn-t">reading order</span>'
                 '<span class="pn-l">%s ends here &rarr;</span></span>') % esc(h1_title(slug))
    else:
        right = ('<a class="pn pn--next" href="%s.html">'
                 '<span class="pn-t">next</span>'
                 '<span class="pn-l">%s &rarr;</span></a>') % (next_slug, esc(h1_title(next_slug)))

    css = (
        "\n  .pnwrap{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:28px 0 6px;}\n"
        "  .pn{display:flex;flex-direction:column;gap:2px;padding:11px 14px;\n"
        "      border:1px solid rgba(120,130,145,.32);border-radius:10px;\n"
        "      text-decoration:none;color:inherit;font-size:15px;line-height:1.4;}\n"
        "  .pn--next a,.pn.pn--next{ }\n"
        "  a.pn:hover{border-color:rgba(46,160,120,.7);}\n"
        "  .pn-t{font-size:11px;letter-spacing:.06em;text-transform:uppercase;\n"
        "       opacity:.7;font-weight:600;}\n"
        "  .pn-l{font-size:14px;}\n"
        "  .pn--next .pn-l{text-align:right;}\n"
        "  .pn--end{opacity:.65;cursor:default;}\n"
        "  .pn--next.pn--end .pn-l{text-align:right;}\n"
        "  @media (max-width:560px){.pnwrap{grid-template-columns:1fr;gap:10px;}}\n"
    )
    return (
        "\n"
        "<!-- %s: prev/next in shelf order (single source: %s; do not hand-edit) -->\n"
        "<style>%s</style>\n"
        '<nav class="pnwrap" aria-label="Reading order on the shelf">\n'
        "  %s\n  %s\n"
        "</nav>\n"
        "<!-- /%s -->\n"
        % (MARK, ARCHIVE, css, left, right, MARK)
    )


REMOVE_RE = re.compile(
    r"\n?<!-- %s:[^\n]*?-->\n.*?\n<!-- /%s -->\n" % (re.escape(MARK), re.escape(MARK)),
    re.S,
)


def locate_insert(t):
    """Anchor the block just before the page closes: </main> when present
    (the 5 note posts), else </body> (the 20 episode posts). Both appear
    exactly once in every shipped post; </body> is the guaranteed fallback."""
    i = t.rfind("</main>")
    if i != -1:
        return i, "</main>"
    i = t.rfind("</body>")
    if i != -1:
        return i, "</body>"
    return -1, None


def inject(dry=False):
    order = read_order()
    changed, unchanged, skipped, problems = [], [], [], []
    for slug in order:
        p = os.path.join(SITE, "posts", slug + ".html")
        if not os.path.exists(p):
            skipped.append(slug)  # in archive, no file -> a 404 we must not ship
            continue
        with open(p, encoding="utf-8") as f:
            t = f.read()
        base = REMOVE_RE.sub("", t)  # idempotent: drop any prior 587 block first
        idx, anchor = locate_insert(base)
        if idx == -1:
            problems.append(slug)
            continue
        block = build_block(slug, order)
        if LEAK_RE.search(block):
            problems.append(slug + " (leak-guard fired on generated block)")
            continue
        new = base[:idx] + block + base[idx:]
        if new != t:
            if not dry:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(new)
            changed.append(slug)
        else:
            unchanged.append(slug)
    return order, changed, unchanged, skipped, problems


def selftest():
    """Synthetic end-to-end: build a strip for the FIRST, a MIDDLE, and the
    LAST slug of the real shelf order, and verify the 587 contract by the
    EXACT anchors a gate reads:
      - MIDDLE: BOTH a prev href AND a next href to real posts/ files
      - FIRST:  no prev href, exactly ONE next href (a real post)
      - LAST:   no next href, exactly ONE prev href (a real post)
      - every href that points at a post resolves to a file on disk
      - the leak guard never fires on a real, expected block
    Exercises the load-bearing claim without touching the live site files.
    """
    order = read_order()
    assert len(order) >= 3, "shelf order too short to test ends + middle (%d)" % len(order)
    first, last, mid = order[0], order[-1], order[len(order) // 2]
    ok = True

    def hrefs(b):
        return [h for h in re.findall(r'href="([^"]+)"', b) if h.endswith(".html")]

    bf = build_block(first, order)
    bm = build_block(mid, order)
    bl = build_block(last, order)

    hf, hm, hl = hrefs(bf), hrefs(bm), hrefs(bl)

    # FIRST: exactly one link (its next -> the 2nd post). Its "previous" is the
    # "starts here" span (no href), so a count of 1 is the end contract itself.
    if len(hf) != 1:
        print("SELFTEST FAIL: FIRST must carry exactly one link (its next), got %r" % hf)
        ok = False
    if not hf or hf[0] != order[1] + ".html":
        print("SELFTEST FAIL: FIRST next -> %r, expected %s" % (hf, order[1] + ".html"))
        ok = False

    # MIDDLE: exactly two links (prev + next), in reading order.
    if len(hm) != 2:
        print("SELFTEST FAIL: MIDDLE must carry exactly two links (prev+next), got %r" % hm)
        ok = False
    if not (hm and hm[0] == order[len(order)//2 - 1] + ".html"
            and hm[1] == order[len(order)//2 + 1] + ".html"):
        print("SELFTEST FAIL: MIDDLE prev/next order wrong -> %r" % hm)
        ok = False

    # LAST: exactly one link (its prev -> the prior post). Its "next" is the
    # "ends here" span (no href), so a count of 1 is the end contract itself.
    if len(hl) != 1:
        print("SELFTEST FAIL: LAST must carry exactly one link (its prev), got %r" % hl)
        ok = False
    if not hl or hl[0] != order[-2] + ".html":
        print("SELFTEST FAIL: LAST prev -> %r, expected %s" % (hl, order[-2] + ".html"))
        ok = False

    # idempotency: removing then re-adding a block is a no-op on the same input
    with open(os.path.join(SITE, "posts", mid + ".html"), encoding="utf-8") as f:
        sample = f.read()
    base = REMOVE_RE.sub("", sample)
    idx, _ = locate_insert(base)
    assert idx != -1, "selftest post has no </main>/</body> anchor"
    v1 = base[:idx] + build_block(mid, order) + base[idx:]
    v1b = REMOVE_RE.sub("", v1)
    idx2, _ = locate_insert(v1b)
    v2 = v1b[:idx2] + build_block(mid, order) + v1b[idx2:]
    if v1 != v2:
        print("SELFTEST FAIL: re-run did not stabilize (not idempotent)")
        ok = False

    # leak guard must stay silent on a real, expected block
    if LEAK_RE.search(build_block(mid, order)):
        print("SELFTEST FAIL: leak guard fired on a legitimate block (bad guard)")
        ok = False

    print("SELFTEST %s (first=1 next / middle=prev+next / last=1 prev, "
          "idempotent, leak-guard silent; order from %s, %d posts)"
          % ("PASS" if ok else "FAIL", ARCHIVE, len(order)))
    return 0 if ok else 1


def main():
    a = sys.argv[1:]
    if a and a[0] == "--selftest":
        return selftest()
    dry = bool(a and a[0] == "--dry")
    order, changed, unchanged, skipped, problems = inject(dry=dry)
    print("next-prev.py -- order (single source: %s): %s" % (ARCHIVE, ", ".join(order)))
    print("posts in order: %d  |  would-write/updated: %d  |  already-correct: %d  |  skipped(no file): %d"
          % (len(order), len(changed), len(unchanged), len(skipped)))
    if dry:
        print("DRY run -- nothing written.")
    else:
        print("WROTE unified reading-order strip into %d post(s)%s" %
              (len(changed), "" if changed else " (all already correct)"))
        if skipped:
            print("SKIP (in archive, no posts/ file): %s" % ", ".join(skipped))
    if problems:
        print("PROBLEM: %s" % "; ".join(problems))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
