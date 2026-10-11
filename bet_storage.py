"""
This houses where the bets are kept.

If the google sheet secrets are set up (see .streamlit/secrets.toml) the bets live in a google sheet, one row per
bet, so every person has their own bets and they survive the app restarting. The sheet needs a tab named "bets"
with the header row: user, league, season, week, team, spread, placed_at (the columns can be in any order)

Without the secrets, your own computer falls back to the local bets/wk<week>.json files, which is one set of bets
per machine. Those files are shared by everybody looking at the page, so a hosted copy never uses them: there,
without the sheet, bets are only kept for the browser tab they were entered in (and the page says so).

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
SHEET_TIMEOUT_SECONDS = 10  # give up on google after this long rather than leaving everybody's page waiting

_lock = threading.Lock()
# every bet row in the sheet as a dictionary of column -> value, shared by everyone using the app
_sheet_cache = {"pulled": 0, "rows": None, "header": None}


def using_sheet():
    return _worksheet() is not None

def load_bets(username, season, week, shared_files=True):
    """
    Returns this person's bets for the week, a dictionary of team -> (spread, timestamp it was entered).
    shared_files says whether the local bet files may be used when there is no sheet (only on your own computer).
    """
    worksheet = _worksheet()
    if worksheet is None:
        return _load_file(week) if shared_files else dict(_tab_bets().get((username.lower(), season, week), {}))
    with _lock:
        rows = _sheet_rows(worksheet)
    bets = {}
    for row in rows:
        if _is_mine(row, username, season, week):
            try:
                bets[str(row["team"])] = (float(row["spread"]), float(row["placed_at"] or 0))
            except (TypeError, ValueError):
                pass  # a row someone typed something odd into by hand shouldn't break everyone else's bets
    return bets

def save_bets(username, league_id, season, week, bets, shared_files=True):
    """Replaces this person's bets for the week with the given dictionary."""
    worksheet = _worksheet()
    if worksheet is None:
        if shared_files:
            _save_file(week, bets)
        else:
            _tab_bets()[(username.lower(), season, week)] = dict(bets)
        return

    with _lock:
        # always work from a fresh read, the row numbers have to be right to delete the old rows
        rows = _sheet_rows(worksheet, fresh=True)
        header = _sheet_cache["header"]
        old_rows = [i for i, row in enumerate(rows) if _is_mine(row, username, season, week)]
        new_rows = [{"user": username.lower(), "league": str(league_id), "season": int(season), "week": int(week),
                     "team": team, "spread": spread, "placed_at": placed_at}
                    for team, (spread, placed_at) in bets.items()]

        # The old rows coming out and the new rows going in are sent as one request, which google applies all
        # or nothing. So a failure half way can't leave someone with their old bets deleted and nothing saved.
        # Deleted bottom up so removing one row doesn't move the ones still to be removed (+1 for the header row).
        requests = [{"deleteDimension": {"range": {"sheetId": worksheet.id, "dimension": "ROWS",
                                                   "startIndex": i + 1, "endIndex": i + 2}}}
                    for i in sorted(old_rows, reverse=True)]
        if new_rows:
            # written in whatever order the sheet's columns are in. Text stays text, so the long league id is kept exact
            requests.append({"appendCells": {
                "sheetId": worksheet.id,
                "fields": "userEnteredValue",
                "rows": [{"values": [_cell(row.get(column, "")) for column in header]} for row in new_rows],
            }})
        if requests:
            worksheet.spreadsheet.batch_update({"requests": requests})
        _sheet_cache["rows"] = [row for i, row in enumerate(rows) if i not in set(old_rows)] + new_rows
        _sheet_cache["pulled"] = time.time()

def _cell(value):
    if isinstance(value, (int, float)):
        return {"userEnteredValue": {"numberValue": value}}
    return {"userEnteredValue": {"stringValue": str(value)}}


######################
# Google sheet
######################

@st.cache_resource(show_spinner=False)
def _worksheet():
    """The sheet tab the bets are in, or None if the secrets for it aren't set up."""
    try:
        if "gcp_service_account" not in st.secrets:
            return None
        account = dict(st.secrets["gcp_service_account"])
        # In a toml file anything under the [gcp_service_account] line belongs to it. So if bets_sheet_id was
        # pasted below that line instead of above it, this is where it ends up, and we look there too.
        sheet_id = st.secrets.get("bets_sheet_id") or account.pop("bets_sheet_id", None)
        if not sheet_id:
            return None
    except Exception:
        return None  # no secrets file at all
    import gspread  # only needed when the sheet is used
    client = gspread.service_account_from_dict(account)
    client.set_timeout(SHEET_TIMEOUT_SECONDS)
    return client.open_by_key(sheet_id).worksheet(SHEET_TAB)

def _sheet_rows(worksheet, fresh=False):
    """
    All the bet rows in the sheet (without the header). Call with _lock held.
    If google can't be reached for a routine re-read we keep showing the copy we already have (and try again in a
    few seconds) rather than making everyone's bets vanish. A fresh read, which saving needs, always raises.
    """
    expired = _sheet_cache["rows"] is None or time.time() - _sheet_cache["pulled"] > SHEET_CACHE_SECONDS
    if fresh or expired:
        try:
            values = worksheet.get_all_values(value_render_option="UNFORMATTED_VALUE")
        except Exception:
            if fresh or _sheet_cache["rows"] is None:
                raise
            _sheet_cache["pulled"] = time.time() - SHEET_CACHE_SECONDS + 10
            return _sheet_cache["rows"]
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
# This browser tab only
######################

def _tab_bets():
    """Bets kept only for the browser tab they were entered in, {(user, season, week): bets}."""
    return st.session_state.setdefault("tab_bets", {})


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
