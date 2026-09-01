"""Checks for Figma comment reading.

No network: `fetch` is the only part that talks to Figma, and everything that
decides what reaches the ledger is pure parsing, which is what these cover.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from figma_parity.comments import (  # noqa: E402
    NO_TOKEN,
    SETUP_HELP,
    CommentSet,
    _parse,
    to_markdown,
    token_from_env,
)

PAYLOAD = {
    "comments": [
        {
            "id": "1",
            "message": "This should be 8px, not 12. We changed it.",
            "user": {"handle": "dana"},
            "created_at": "2026-08-01T10:00:00Z",
            "client_meta": {"node_id": "1:2", "node_offset": {"x": 4, "y": 4}},
            "resolved_at": None,
            "parent_id": "",
        },
        {
            "id": "2",
            "message": "Agreed",
            "user": {"handle": "sam"},
            "created_at": "2026-08-01T11:00:00Z",
            "client_meta": {"node_id": "1:2"},
            "resolved_at": None,
            "parent_id": "1",
        },
        {
            "id": "3",
            "message": "Old note nobody cares about",
            "user": {"handle": "dana"},
            "created_at": "2026-07-01T10:00:00Z",
            "client_meta": {"node_id": "1:2"},
            "resolved_at": "2026-07-02T10:00:00Z",
            "parent_id": "",
        },
        {
            "id": "4",
            "message": "Whole screen feels cramped",
            "user": {"handle": "kim"},
            "created_at": "2026-08-02T10:00:00Z",
            "client_meta": {"x": 100, "y": 200},
            "resolved_at": None,
            "parent_id": "",
        },
        {
            "id": "5",
            "message": "Note on a node we are not implementing",
            "user": {"handle": "kim"},
            "created_at": "2026-08-02T10:00:00Z",
            "client_meta": {"node_id": "99:99"},
            "resolved_at": None,
            "parent_id": "",
        },
    ]
}


def test_parses_nodes_authors_and_resolution():
    cs = _parse(PAYLOAD)
    assert len(cs.comments) == 5
    first = cs.comments[0]
    assert first.node_id == "1:2"
    assert first.author == "dana"
    assert first.created_at == "2026-08-01"
    assert not first.resolved
    assert cs.comments[2].resolved


def test_resolved_comments_are_not_requirements():
    cs = _parse(PAYLOAD)
    assert all(not c.resolved for c in cs.unresolved())
    assert "Old note nobody cares about" not in to_markdown(cs)


def test_replies_are_threaded_not_listed_as_separate_rows():
    cs = _parse(PAYLOAD)
    assert cs.comments[1].is_reply
    md = to_markdown(cs)
    assert "1 reply" in md, md
    # the reply's own text must not become its own requirement row
    assert md.count("| 1:2 |") == 1, md


def test_scoping_to_the_nodes_actually_being_implemented():
    cs = _parse(PAYLOAD)
    scoped = cs.for_nodes({"1:2"})
    ids = {c.id for c in scoped}
    assert "5" not in ids, "a comment on an unrelated node must not be pulled in"
    assert "4" in ids, "a canvas-pinned comment still applies to the screen"


def test_canvas_pinned_comments_are_kept():
    md = to_markdown(_parse(PAYLOAD), {"1:2"})
    assert "(canvas)" in md
    assert "cramped" in md


def test_every_comment_starts_open():
    md = to_markdown(_parse(PAYLOAD))
    body = [l for l in md.splitlines() if l.startswith("| ") and "author" not in l]
    assert body, md
    assert all("☐" in row for row in body), "a comment someone wrote is a requirement"


def test_pipes_in_a_comment_cannot_break_the_table():
    payload = {
        "comments": [
            {
                "id": "1",
                "message": "use | not / here\nand mind the wrap",
                "user": {"handle": "dana"},
                "created_at": "2026-08-01T10:00:00Z",
                "client_meta": {"node_id": "1:2"},
                "resolved_at": None,
                "parent_id": "",
            }
        ]
    }
    import re

    row = [l for l in to_markdown(_parse(payload)).splitlines() if l.startswith("| 1:2")][0]
    assert "\\|" in row, f"the pipe in the comment was not escaped: {row}"
    assert "\n" not in row, "a newline would split one comment across two rows"
    # Unescaped pipes are the cell delimiters; there must still be exactly five cells.
    cells = re.split(r"(?<!\\)\|", row)[1:-1]
    assert len(cells) == 5, f"table shape broken, got {len(cells)} cells: {cells}"


def test_empty_and_all_resolved_read_differently():
    """"no comments" and "comments, all resolved" are different facts."""
    assert "None on this file" in to_markdown(CommentSet())

    only_resolved = {"comments": [dict(PAYLOAD["comments"][2])]}
    md = to_markdown(_parse(only_resolved))
    assert "None open" in md, md
    assert "resolved" in md, "must say the comments existed and were resolved"


def test_missing_token_is_reported_as_setup_not_failure():
    import os

    saved = {k: os.environ.pop(k, None) for k in
             ("FIGMA_TOKEN", "FIGMA_ACCESS_TOKEN", "FIGMA_PERSONAL_ACCESS_TOKEN")}
    try:
        assert token_from_env() is None
        assert NO_TOKEN == 3, "a distinct exit code, so 'not configured' != 'broken'"
        assert "file_comments:read" in SETUP_HELP
        assert "never written to disk" in SETUP_HELP
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_blank_token_counts_as_absent():
    import os

    os.environ["FIGMA_TOKEN"] = "   "
    try:
        assert token_from_env() is None
    finally:
        del os.environ["FIGMA_TOKEN"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  ok   {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
