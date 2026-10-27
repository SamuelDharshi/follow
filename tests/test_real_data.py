"""Tests on data the recorder actually captured from Strike mainnet (data/follow.db). Skipped if no data yet."""
import os

import pytest

from follow import config, db
from follow.book import BookError
from follow.strike_l3 import Resync, check_sequence
from follow.verify import diff, replay

pytestmark = pytest.mark.skipif(not os.path.exists(config.DB_PATH), reason="no recorded data")


@pytest.fixture(scope="module")
def con():
    return db.connect(config.DB_PATH, readonly=True)


def pair(con):
    """A recorded session start snapshot and a later checkpoint snapshot from the same session."""
    row = con.execute("""SELECT c.id, c.session, c.last_sequence FROM snapshots c WHERE c.kind='checkpoint' ORDER BY c.id DESC LIMIT 1""").fetchone()
    if not row:
        pytest.skip("no checkpoint snapshot recorded yet")
    start = con.execute("SELECT body FROM snapshots WHERE session=? AND kind='session_start'", (row[1],)).fetchone()
    cp = con.execute("SELECT body FROM snapshots WHERE id=?", (row[0],)).fetchone()
    return row[1], row[2], db.load_snapshot(start[0]), db.load_snapshot(cp[0])


def test_replay_matches_later_rest_snapshot(con):
    session, seq, start, cp = pair(con)
    assert diff(replay(con, session, start, seq), cp) == 0


def test_dropping_one_recorded_event_corrupts_the_book(con):
    """Why a sequence gap forces a rebuild: replaying real events minus one no longer matches the exchange."""
    session, seq, start, cp = pair(con)
    victim = con.execute("SELECT sequence FROM l3_events WHERE session=? AND sequence>? AND sequence<=? AND action='cancel' "
                         "ORDER BY sequence LIMIT 1 OFFSET 50", (session, start["last_sequence"], seq)).fetchone()
    if not victim:
        pytest.skip("not enough events")
    try:
        d = diff(replay(con, session, start, seq, drop_sequence=victim[0]), cp)
    except BookError:
        return  # also a detected corruption
    assert d > 0


def test_recorded_sequences_have_no_holes_and_a_dropped_one_is_flagged(con):
    seqs = [r[0] for r in con.execute("SELECT sequence FROM l3_events WHERE session=(SELECT MAX(session) FROM l3_events) ORDER BY sequence LIMIT 2000")]
    assert len(seqs) > 10
    expected = seqs[0]
    for s in seqs:
        assert check_sequence(s, expected)
        expected = s + 1
    holed = seqs[:5] + seqs[6:]
    expected = holed[0]
    with pytest.raises(Resync):
        for s in holed:
            check_sequence(s, expected)
            expected = s + 1
