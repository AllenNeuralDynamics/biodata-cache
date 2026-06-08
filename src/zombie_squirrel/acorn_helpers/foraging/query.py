"""DuckDB query helpers for the foraging parquet database.

Two layers — reach for the simple helpers first, drop to native SQL when you need more:

  Layer 1 (convenience):
      select_sessions -> fetch_trials / fetch_events
    Filter the (small) session table on any metric / metadata, then pull those sessions'
    trials or events with the session metadata already joined on — in one call.

  Layer 0 (escape hatch):
      read_trials / read_events
    Return a fast, partition-scoped ``read_parquet(...)`` clause for a set of subjects.
    Drop it into whatever SQL you write — aggregations, window functions, trial<->event
    joins, custom GROUP BY.

Everything reads the public S3 database (no AWS credentials needed). Pass ``base=`` to
redirect to a local build or a custom S3 path.

Ported from aind-dynamic-foraging-database with minor adaptations.
"""

import duckdb

PROD_S3_PREFIX = "s3://aind-scratch-data/aind-dynamic-foraging-cache"
SESSION_DB = f"{PROD_S3_PREFIX}/session_table.parquet"
TRIAL_DB = f"{PROD_S3_PREFIX}/trial_table"
EVENT_DB = f"{PROD_S3_PREFIX}/event_table"

DEFAULT_TRIAL_COLUMNS = [
    "trial", "animal_response", "earned_reward",
    "reward_probabilityL", "reward_probabilityR",
]
DEFAULT_EVENT_COLUMNS = ["trial", "timestamps", "event", "data"]

_KEYS = ("subject_id", "session_date", "session_id")

_SCOPED_MAX = 100
_PARTITION_CACHE: dict[str, set] = {}


def _conn(con):
    return con if con is not None else duckdb


def _quote_in(values):
    return ", ".join("'" + str(v).replace("'", "''") + "'" for v in values)


def _partition_subjects(base, con=None):
    """Subject ids that have a partition file under ``base`` (memoized per base)."""
    cached = _PARTITION_CACHE.get(base)
    if cached is not None:
        return cached
    rows = _conn(con).sql(f"SELECT file FROM glob('{base}/subject_id=*/*.parquet')").df()
    found = rows["file"].str.extract(r"subject_id=([^/]+)/", expand=False).dropna()
    _PARTITION_CACHE[base] = result = set(found)
    return result


def clear_caches():
    """Drop memoized partition listings (call after rebuilding a local cache in-session)."""
    _PARTITION_CACHE.clear()


def _full_glob(base):
    return f"read_parquet('{base}/**/*.parquet', hive_partitioning=true, union_by_name=true)"


def _scoped_read(base, subjects, con):
    if subjects is None:
        return _full_glob(base)
    want = sorted({str(s) for s in subjects} & _partition_subjects(base, con))
    if not want:
        return f"(SELECT * FROM {_full_glob(base)} WHERE false)"
    if len(want) > _SCOPED_MAX:
        return (
            f"(SELECT * FROM {_full_glob(base)} "
            f"WHERE CAST(subject_id AS VARCHAR) IN ({_quote_in(want)}))"
        )
    files = [f"'{base}/subject_id={s}/*.parquet'" for s in want]
    return f"read_parquet([{', '.join(files)}], hive_partitioning=true, union_by_name=true)"


# ---------------------------------------------------------------------------
# Layer 0 — escape hatch: a fast, partition-scoped read_parquet(...) source
# ---------------------------------------------------------------------------

def read_trials(subjects=None, base=None, con=None):
    """Return a ``read_parquet(...)`` clause for the trial table, scoped to ``subjects``.

    Drop the returned string into any SQL::

        src = read_trials(['754372', '758435'])
        duckdb.sql(f"SELECT subject_id, AVG(earned_reward::DOUBLE) FROM {src} GROUP BY subject_id")

    Parameters
    ----------
    subjects : iterable, optional
        Subject ids to scope the read to. ``None`` reads the full table.
    base : str, optional
        Trial-table directory prefix (default: production S3 ``trial_table``).
    con : duckdb connection, optional
    """
    return _scoped_read(base or TRIAL_DB, subjects, con)


def read_events(subjects=None, base=None, con=None):
    """Return a ``read_parquet(...)`` clause for the event table, scoped to ``subjects``.

    Parameters
    ----------
    subjects : iterable, optional
    base : str, optional
        Event-table directory prefix (default: production S3 ``event_table``).
    con : duckdb connection, optional
    """
    return _scoped_read(base or EVENT_DB, subjects, con)


# ---------------------------------------------------------------------------
# Layer 1 — convenience: filter sessions, then fetch their trials / events
# ---------------------------------------------------------------------------

def select_sessions(where=None, subjects=None, columns=None, base=None, con=None,
                    order_by="subject_id, session_date"):
    """Filter the session table; return selected sessions as a DataFrame.

    Parameters
    ----------
    where : str, optional
        Raw SQL predicate, e.g. ``"task LIKE '%Uncoupled%' AND foraging_eff > 0.8"``.
    subjects : iterable, optional
        Restrict to these subject ids.
    columns : list[str], optional
        Extra session-metadata columns to carry onto trials/events. ``_session_id``,
        ``subject_id``, ``session_date`` are always included.
    base : str, optional
        Session parquet file path (default: production S3 ``session_table.parquet``).
    con : duckdb connection, optional
    order_by : str, optional
        SQL ORDER BY clause (default: ``"subject_id, session_date"``).

    Returns
    -------
    pandas.DataFrame
        One row per selected session, with ``_session_id`` as the join key.
    """
    base = base or SESSION_DB
    extra = [c for c in (columns or []) if c not in ("_session_id", *_KEYS)]
    sel_cols = ", ".join(["_session_id", "subject_id", "session_date", *extra])
    clauses = []
    if subjects is not None:
        clauses.append(f"subject_id IN ({_quote_in(subjects)})")
    if where:
        clauses.append(f"({where})")
    where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    order_sql = f"ORDER BY {order_by}" if order_by else ""
    return _conn(con).sql(
        f"SELECT {sel_cols} FROM read_parquet('{base}') {where_sql} {order_sql}"
    ).df()


def fetch_trials(sessions, columns=None, base=None, con=None):
    """Pull trial rows for a set of selected sessions, with session metadata joined on.

    Parameters
    ----------
    sessions : pandas.DataFrame
        Selected sessions from :func:`select_sessions`. Must contain ``_session_id``
        and ``subject_id``; every other column is carried onto each trial row.
    columns : list[str] or "*", optional
        Trial columns to project (default: small choice/reward set). ``"*"`` returns all.
    base : str, optional
        Trial-table directory prefix (default: production S3).
    con : duckdb connection, optional

    Returns
    -------
    pandas.DataFrame
        One row per trial, ordered by ``subject_id, session_date, trial``.
    """
    return _fetch(sessions, base or TRIAL_DB, columns or DEFAULT_TRIAL_COLUMNS,
                  con, order_tail="trial", lead="trial")


def fetch_events(sessions, events=None, columns=None, base=None, con=None):
    """Pull event rows for a set of selected sessions, with session metadata joined on.

    Parameters
    ----------
    sessions : pandas.DataFrame
        Selected sessions from :func:`select_sessions`.
    events : iterable, optional
        Restrict to these event types, e.g. ``['left_lick_time', 'right_lick_time']``.
    columns : list[str] or "*", optional
        Event columns to project (default: ``trial, timestamps, event, data``).
    base : str, optional
        Event-table directory prefix (default: production S3).
    con : duckdb connection, optional

    Returns
    -------
    pandas.DataFrame
        One row per event, ordered by ``subject_id, session_date, timestamps``.
    """
    extra_where = f"t.event IN ({_quote_in(events)})" if events else None
    return _fetch(sessions, base or EVENT_DB, columns or DEFAULT_EVENT_COLUMNS,
                  con, order_tail="timestamps", extra_where=extra_where)


def _fetch(sessions, base, columns, con, order_tail, extra_where=None, lead=None):
    import pandas as pd

    if len(sessions) == 0:
        return pd.DataFrame()
    conn = _conn(con)
    src = _scoped_read(base, sessions["subject_id"].unique().tolist(), con)
    conn.register("_sel_sessions", sessions)
    try:
        try:
            return _run_fetch(conn, src, sessions, columns, order_tail, extra_where, None, lead)
        except duckdb.BinderException:
            avail = set(conn.sql(f"DESCRIBE SELECT * FROM {src}").df()["column_name"])
            return _run_fetch(conn, src, sessions, columns, order_tail, extra_where, avail, lead)
    finally:
        conn.unregister("_sel_sessions")


def _col_expr(col, avail):
    return f"t.{col}" if (avail is None or col in avail) else f"CAST(NULL AS DOUBLE) AS {col}"


def _run_fetch(conn, src, sessions, columns, order_tail, extra_where, avail, lead=None):
    meta = [f"s.{c}" for c in sessions.columns if c not in ("_session_id", *_KEYS)]
    lead_proj = [_col_expr(lead, avail)] if lead else []
    if columns in ("*", ["*"]):
        excl = [k for k in _KEYS if avail is None or k in avail]
        if lead and (avail is None or lead in avail):
            excl.append(lead)
        proj = [f"t.* EXCLUDE ({', '.join(excl)})"]
    else:
        proj = [_col_expr(c, avail) for c in columns if c not in _KEYS and c != lead]
    select = ", ".join(["s.subject_id", "s.session_date", "t.session_id", *lead_proj, *meta, *proj])
    where_sql = f"WHERE {extra_where}" if extra_where else ""
    order = ["s.subject_id", "s.session_date"]
    if avail is None or order_tail in avail:
        order.append(f"t.{order_tail}")
    return conn.sql(f"""
        SELECT {select}
        FROM {src} t
        JOIN _sel_sessions s ON t.session_id = s._session_id
        {where_sql}
        ORDER BY {', '.join(order)}
    """).df()
