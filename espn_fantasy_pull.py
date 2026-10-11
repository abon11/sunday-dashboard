"""
This houses all of the code to pull fantasy lineups from an ESPN fantasy league, giving back the same Lineup and
Player objects that sleeper_pull does so the dashboard doesn't care which site a league is on.

Like the rest of espn's api this is unofficial. It only works for leagues that are viewable to the public
(League Manager Tools -> Basic Settings -> "Make League Viewable to Public"). A private league needs the login
cookies of someone in it, which we don't ask for.
"""
import json
import time

import requests

from sleeper_pull import Player, Lineup, current_nfl_season

API = 'https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons'
STATIC_TTL = 3600  # seconds to reuse the things that don't change during a slate (teams, settings)
LIVE_TTL = 8       # seconds to reuse the live scores, so everyone looking at the same league shares one pull

_session = requests.Session()
_session.headers["User-Agent"] = "Mozilla/5.0"  # espn turns away the default python one
_response_cache = {}  # (url, params, filter) -> (time to drop it, json)

# espn's lineup slot ids, named the way sleeper_pull.Lineup.order_list understands them
SLOT_NAMES = {0: "QB", 1: "QB", 2: "RB", 3: "FLEX", 4: "WR", 5: "FLEX", 6: "TE", 7: "SUPER_FLEX",
              8: "DL", 9: "DL", 10: "LB", 11: "DL", 12: "DB", 13: "DB", 14: "DB", 15: "IDP_FLEX",
              16: "D/ST", 17: "K", 18: "P", 19: "HC", 20: "BN", 21: "IR", 23: "FLEX", 24: "DL"}
BENCH_SLOT_IDS = (20, 21)
# the order the slots are shown in: the positions, then the flex spots, then defense and kicker
SLOT_ORDER = (0, 1, 2, 4, 6, 3, 5, 23, 7, 8, 9, 11, 24, 10, 12, 13, 14, 15, 16, 17, 18, 19)
POSITION_NAMES = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 7: "P", 9: "DT", 10: "DE", 11: "LB",
                  12: "CB", 13: "S", 14: "HC", 16: "D/ST"}

# names for espn's stat ids in the scoring breakdown (anything missing is shown as "Stat <id>")
STAT_LABELS = {
    0: "Pass Attempts", 1: "Completions", 2: "Incompletions", 3: "Passing Yards", 4: "Passing TD",
    15: "40+ Yard Passing TD", 16: "50+ Yard Passing TD", 17: "300-399 Passing Yards", 18: "400+ Passing Yards",
    19: "2-Pt Pass", 20: "Interceptions Thrown", 23: "Rush Attempts", 24: "Rushing Yards", 25: "Rushing TD",
    26: "2-Pt Rush", 35: "40+ Yard Rushing TD", 36: "50+ Yard Rushing TD", 37: "100-199 Rushing Yards",
    38: "200+ Rushing Yards", 42: "Receiving Yards", 43: "Receiving TD", 44: "2-Pt Reception",
    45: "40+ Yard Receiving TD", 46: "50+ Yard Receiving TD", 53: "Receptions", 56: "100-199 Receiving Yards",
    57: "200+ Receiving Yards", 58: "Targets", 63: "Fumble Recovery TD", 64: "Times Sacked", 68: "Fumbles",
    72: "Fumbles Lost", 74: "FG 50+", 77: "FG 40-49", 80: "FG 0-39", 85: "FG Missed", 86: "PAT Made",
    88: "PAT Missed", 89: "0 Points Allowed", 90: "1-6 Points Allowed", 91: "7-13 Points Allowed",
    92: "14-17 Points Allowed", 93: "Blocked Kick TD", 95: "Interceptions", 96: "Fumble Recoveries",
    97: "Blocked Kicks", 98: "Safeties", 99: "Sacks", 101: "Kick Return TD", 102: "Punt Return TD",
    103: "Interception Return TD", 104: "Fumble Return TD", 106: "Forced Fumbles", 107: "Assisted Tackles",
    108: "Solo Tackles", 109: "Total Tackles", 113: "Passes Defensed", 114: "Kick Return Yards",
    115: "Punt Return Yards", 121: "18-21 Points Allowed", 122: "22-27 Points Allowed",
    123: "28-34 Points Allowed", 124: "35-45 Points Allowed", 125: "46+ Points Allowed",
    129: "100-199 Yards Allowed", 130: "200-299 Yards Allowed", 131: "300-349 Yards Allowed",
    132: "350-399 Yards Allowed", 133: "400-449 Yards Allowed", 134: "450-499 Yards Allowed",
    135: "500-549 Yards Allowed", 136: "550+ Yards Allowed", 198: "FG 50-59", 201: "FG 60+",
    206: "2-Pt Return", 209: "1-Pt Safety",
}


def _get(league_id, views, ttl, week=None, matchup_period=None):
    """
    GETs the given views of a league and returns the json, reusing a response for ttl seconds.
    Raises a ValueError with a message meant for the person looking at the dashboard if the league can't be read.
    """
    url = f'{API}/{current_nfl_season()}/segments/0/leagues/{league_id}'
    params = [("view", view) for view in views] + ([("scoringPeriodId", week)] if week else [])
    # without this filter espn sends every matchup of the season
    fantasy_filter = json.dumps({"schedule": {"filterMatchupPeriodIds": {"value": [matchup_period]}}}) if matchup_period else None

    now = time.time()
    key = (url, tuple(params), fantasy_filter)
    cached = _response_cache.get(key)
    if cached and cached[0] > now:
        return cached[1]
    for old_key in [k for k, (expires, _) in _response_cache.items() if expires <= now]:
        _response_cache.pop(old_key, None)  # so the cache doesn't grow forever

    resp = _session.get(url, params=params, timeout=10,
                        headers={"x-fantasy-filter": fantasy_filter} if fantasy_filter else None)
    if resp.status_code == 401:
        raise ValueError(f"ESPN league {league_id} is private. Its league manager has to turn on "
                         "'Make League Viewable to Public' in the league's Basic Settings.")
    if resp.status_code in (400, 404):
        raise ValueError(f"ESPN league '{league_id}' was not found for the {current_nfl_season()} season.")
    resp.raise_for_status()
    data = resp.json()
    _response_cache[key] = (now + ttl, data)
    return data

def _pro_teams():
    """Dictionary of espn's NFL team id -> abbreviation, the same abbreviations espn_pull's games use."""
    cached = _response_cache.get("pro_teams")
    if cached and cached[0] > time.time():
        return cached[1]
    resp = _session.get("https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams", timeout=10)
    resp.raise_for_status()
    teams = {int(t["team"]["id"]): t["team"]["abbreviation"] for t in resp.json()["sports"][0]["leagues"][0]["teams"]}
    _response_cache["pro_teams"] = (time.time() + 24 * 3600, teams)
    return teams

def _league_info(league_id):
    return _get(league_id, ("mTeam", "mSettings"), STATIC_TTL)

def league_teams(league_id):
    """
    Returns a list of (team id, team name, owner's espn name) for every team in the league, for picking which
    one is yours. ESPN has no public username to look a team up by like sleeper does.
    """
    info = _league_info(league_id)
    members = {m["id"]: m.get("displayName") or "" for m in info.get("members") or []}
    return [(team["id"], _team_name(team), members.get(team.get("primaryOwner"), ""))
            for team in sorted(info.get("teams") or [], key=lambda t: t["id"])]

def _team_name(team):
    return (team.get("name") or f'{team.get("location") or ""} {team.get("nickname") or ""}').strip() or f'Team {team["id"]}'

def pull_lineup(league_id, team_id, week):
    """
    Returns (my Lineup, opponent's Lineup) for the given team in the given week, the same as
    sleeper_pull.pull_lineup(..., roster='both'). If there is no opponent that week, their Lineup is empty.
    """
    team_id = int(team_id)
    info = _league_info(league_id)
    teams = {team["id"]: team for team in info.get("teams") or []}
    if team_id not in teams:
        raise ValueError(f"Team {team_id} was not found in ESPN league {league_id}.")
    members = {m["id"]: m.get("displayName") or "" for m in info.get("members") or []}
    settings = info.get("settings") or {}

    # the league's starting slots, in display order
    slot_counts = (settings.get("rosterSettings") or {}).get("lineupSlotCounts") or {}
    roster_positions = [SLOT_NAMES[slot] for slot in SLOT_ORDER for _ in range(slot_counts.get(str(slot), 0))]

    # a matchup can cover more than one week (two week playoff rounds), so find the one this week is part of
    matchup_periods = (settings.get("scheduleSettings") or {}).get("matchupPeriods") or {}
    matchup_period = next((int(period) for period, weeks in matchup_periods.items() if week in weeks), week)

    data = _get(league_id, ("mBoxscore",), LIVE_TTL, week=week, matchup_period=matchup_period)
    pro_teams = _pro_teams()

    def build_lineup(side):
        if not side:
            return Lineup([], "---", "No opponent", roster_positions or None)
        team = teams.get(side.get("teamId"), {"id": side.get("teamId")})
        entries = (side.get("rosterForCurrentScoringPeriod") or {}).get("entries") or []
        players = [_build_player(entry, week, pro_teams) for entry in entries if entry.get("lineupSlotId") not in BENCH_SLOT_IDS]
        owner = members.get(team.get("primaryOwner"), "") or team.get("abbrev") or ""
        return Lineup(players, owner, _team_name(team), roster_positions or None)

    for matchup in data.get("schedule") or []:
        if matchup.get("matchupPeriodId") != matchup_period:
            continue
        home, away = matchup.get("home"), matchup.get("away")
        if home and home.get("teamId") == team_id:
            return build_lineup(home), build_lineup(away)
        if away and away.get("teamId") == team_id:
            return build_lineup(away), build_lineup(home)
    raise ValueError(f"No matchup found for {_team_name(teams[team_id])} in week {week}.")

def _build_player(entry, week, pro_teams):
    pool_entry = entry.get("playerPoolEntry") or {}
    player = pool_entry.get("player") or {}

    # each player comes with their real stat line (statSourceId 0) and their projection (1) for the week
    actual, projected = {}, {}
    for stat_line in player.get("stats") or []:
        if stat_line.get("scoringPeriodId") == week and stat_line.get("statSplitTypeId") == 1:
            if stat_line.get("statSourceId") == 0:
                actual = stat_line
            elif stat_line.get("statSourceId") == 1:
                projected = stat_line

    points = actual.get("appliedTotal")
    if points is None:
        points = pool_entry.get("appliedStatTotal") or 0
    built = Player(player.get("firstName") or "",
                   player.get("lastName") or "",
                   POSITION_NAMES.get(player.get("defaultPositionId"), "None"),
                   entry.get("injuryStatus"),
                   round(points, 2),
                   pro_teams.get(player.get("proTeamId"), "--"),
                   None,
                   projected.get("appliedTotal") or 0)

    # every stat that scored (or cost) them something: (stat, amount, points per, points)
    amounts = actual.get("stats") or {}
    for stat_id, stat_points in (actual.get("appliedStats") or {}).items():
        if not stat_points:
            continue
        amount = amounts.get(stat_id) or 0
        label = STAT_LABELS.get(int(stat_id), f"Stat {stat_id}")
        built.breakdown.append((label, amount, round(stat_points / amount, 4) if amount else stat_points, stat_points))
    return built
