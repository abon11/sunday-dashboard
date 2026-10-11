"""
This houses where the bets are kept.

If the google sheet secrets are set up (see .streamlit/secrets.toml) the bets live in a google sheet, one row per
bet, so every person has their own bets and they survive the app restarting. The sheet needs a tab named "bets"
with the header row: user, league, season, week, team, spread, placed_at (the columns can be in any order)

Without the secrets it falls back to the local bets/wk<week>.json files, which is one set of bets per machine.

Either way a set of bets is a dictionary of team -> (spread, timestamp it was entered).
"""
import json
import os
import threading
import time

import streamlit as st

SHEET_TAB = "bets"
SHEET_COLUMNS = ["user", "league", "season", "week", "team", "spread", "placed_at"]
SHEET_CACHE_SECONDS = 60  # google limits reads to ~60 a minute, so the sheet is re-read at most this often

_lock = threading.Lock()
# every bet row in the sheet as a dictionary of column -> value, shared by everyone using the app
_sheet_cache = {"pulled": 0, "rows": None, "header": None}


def using_sheet():
    return _worksheet() is not None

def load_bets(username, season, week):
    """Returns this person's bets for the week, a dictionary of team -> (spread, timestamp it was entered)."""
    worksheet = _worksheet()
    if worksheet is None:
        return _load_file(week)
    with _lock:
        rows = _sheet_rows(worksheet)
    return {row["team"]: (float(row["spread"]), float(row["placed_at"]))
            for row in rows if _is_mine(row, username, season, week)}

def save_bets(username, league_id, season, week, bets):
    """Replaces this person's bets for the week with the given dictionary."""
    worksheet = _worksheet()
    if worksheet is None:
        _save_file(week, bets)
        return

    with _lock:
        # always work from a fresh read, the row numbers have to be right to delete the old rows
        rows = _sheet_rows(worksheet, fresh=True)
        old_rows = [i for i, row in enumerate(rows) if _is_mine(row, username, season, week)]
        new_rows = [{"user": username.lower(), "league": str(league_id), "season": int(season), "week": int(week),
                     "team": team, "spread": spread, "placed_at": placed_at}
                    for team, (spread, placed_at) in bets.items()]
        if old_rows:
            # bottom up so deleting one row doesn't move the ones still to be deleted (+1 for the header row)
            worksheet.spreadsheet.batch_update({"requests": [
                {"deleteDimension": {"range": {"sheetId": worksheet.id, "dimension": "ROWS",
                                               "startIndex": i + 1, "endIndex": i + 2}}}
                for i in sorted(old_rows, reverse=True)
            ]})
        if new_rows:
            # written in whatever order the sheet's columns are in. RAW keeps the long league id as text
            header = _sheet_cache["header"]
            worksheet.append_rows([[row.get(column, "") for column in header] for row in new_rows],
                                  value_input_option="RAW")
        _sheet_cache["rows"] = [row for i, row in enumerate(rows) if i not in set(old_rows)] + new_rows
        _sheet_cache["pulled"] = time.time()


######################
# Google sheet
######################

@st.cache_resource(show_spinner=False)
def _worksheet():
    """The sheet tab the bets are in, or None if the secrets for it aren't set up."""
    try:
        if "gcp_service_account" not in st.secrets or "bets_sheet_id" not in st.secrets:
            return None
    except Exception:
        return None  # no secrets file at all
    import gspread  # only needed when the sheet is used
    client = gspread.service_account_from_dict(dict(st.secrets["gcp_service_account"]))
    return client.open_by_key(st.secrets["bets_sheet_id"]).worksheet(SHEET_TAB)

def _sheet_rows(worksheet, fresh=False):
    """All the bet rows in the sheet (without the header). Call with _lock held."""
    if fresh or _sheet_cache["rows"] is None or time.time() - _sheet_cache["pulled"] > SHEET_CACHE_SECONDS:
        values = worksheet.get_all_values(value_render_option="UNFORMATTED_VALUE")
        header = [str(column).strip().lower() for column in values[0]] if values else []
        missing = [column for column in SHEET_COLUMNS if column not in header]
        if missing:
            raise ValueError(f"the '{SHEET_TAB}' tab of the bets sheet is missing the column(s): {', '.join(missing)}")
        _sheet_cache["header"] = header
        _sheet_cache["rows"] = [dict(zip(header, row)) for row in values[1:]]
        _sheet_cache["pulled"] = time.time()
    return _sheet_cache["rows"]

def _is_mine(row, username, season, week):
    # bets belong to the person, not to one league: they are the same NFL games whichever league is open
    return (str(row.get("user", "")).lower() == username.lower() and str(row.get("season")) == str(season)
            and str(row.get("week")) == str(week) and row.get("spread", "") != "")


######################
# Local files
######################

def _bet_file(week):
    return f'bets/wk{week}.json'

def _load_file(week):
    if not os.path.exists(_bet_file(week)):
        return {}
    with open(_bet_file(week), 'r') as f:
        bets = json.load(f)
    return {team: tuple(bet) for team, bet in bets.items() if bet[0] is not None}

def _save_file(week, bets):
    os.makedirs(os.path.dirname(_bet_file(week)), exist_ok=True)
    with open(_bet_file(week), 'w') as f:
        json.dump(bets, f, indent=4)
