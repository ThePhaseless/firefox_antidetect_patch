#!/usr/bin/env python3
"""The latest PUBLISHED engine release of a repository: the one the gate compares a candidate with.

A release counts when it is not a draft, not a prerelease, and its tag is exactly `firefox-<N>` (digits only: `firefox-69-candidate` and the like
never count). The highest N wins (--rank 2: the one before it, --rank 3: the one before that, and so on). Nothing else decides it: no tag is written in
any workflow, so a new release is the new baseline.

    python scripts/ci/published_release.py --repo <owner/repo> [--rank N] [--github-output <file> --name <key>] [--github-env <file> --name <VAR>]

The CLI reads `gh api repos/<repo>/releases --paginate` (GH_TOKEN from the environment), prints the tag, and writes `<name>=<tag>` to the given
GITHUB_OUTPUT and/or GITHUB_ENV file. It exits 1 with a message when no release qualifies (or fewer than --rank do).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

TAG_RE = re.compile(r"firefox-(\d+)")


class NoPublishedRelease(Exception):
    pass


def parse_pages(text: str) -> list:
    """The releases of `gh api --paginate`: one JSON array per page, written one after the other (or a single array)."""
    decoder = json.JSONDecoder()
    releases, pos, text = [], 0, text.strip()
    while pos < len(text):
        value, pos = decoder.raw_decode(text, pos)
        releases.extend(value if isinstance(value, list) else [value])
        while pos < len(text) and text[pos].isspace():
            pos += 1
    return releases


def latest_published(releases, rank: int = 1) -> str:
    """The tag of the `rank`-th highest `firefox-<N>` that is neither a draft nor a prerelease (1 = the latest, 2 = the one before it);
    NoPublishedRelease when there are fewer than `rank` of them."""
    if rank < 1:
        raise ValueError("rank must be 1 or more, got %d" % rank)
    found = {}
    for release in releases or []:
        if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
            continue
        tag = release.get("tag_name")
        match = TAG_RE.fullmatch(tag) if isinstance(tag, str) else None
        if match:
            found[int(match.group(1))] = tag
    ordered = sorted(found, reverse=True)
    if len(ordered) < rank:
        raise NoPublishedRelease("no published release named firefox-<N> (not a draft, not a prerelease) in the release list" if not ordered else
                                 "only %d published release(s) named firefox-<N>, rank %d was asked" % (len(ordered), rank))
    return found[ordered[rank - 1]]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--rank", type=int, default=1, help="1 = the latest published release (default), 2 = the one before it, ...")
    parser.add_argument("--github-output", help="a GITHUB_OUTPUT file to append <name>=<tag> to")
    parser.add_argument("--github-env", help="a GITHUB_ENV file to append <name>=<tag> to")
    parser.add_argument("--name", help="the key or variable to write")
    args = parser.parse_args(argv)
    if (args.github_output or args.github_env) and not args.name:
        parser.error("--name is required with --github-output or --github-env")
    run = subprocess.run(["gh", "api", "repos/%s/releases" % args.repo, "--paginate"], capture_output=True, text=True)
    if run.returncode != 0:
        print("ERROR: gh api repos/%s/releases failed (%d): %s" % (args.repo, run.returncode, run.stderr.strip()), file=sys.stderr)
        return 1
    try:
        tag = latest_published(parse_pages(run.stdout), args.rank)
    except (NoPublishedRelease, ValueError) as error:
        print("ERROR: %s (repository %s)" % (error, args.repo), file=sys.stderr)
        return 1
    for path in (args.github_output, args.github_env):
        if path:
            with open(path, "a", encoding="utf-8", newline="\n") as handle:
                handle.write("%s=%s\n" % (args.name, tag))
    print(tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
