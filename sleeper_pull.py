import requests
import json
from datetime import datetime
import os
import threading
import time

API = 'https://api.sleeper.app/v1'
STATIC_TTL = 3600  # seconds to reuse league info that basically never changes mid-slate (rosters, users)
LIVE_TTL = 8       # seconds to reuse the live pulls (matchups, stats), so everyone on the dashboard shares one pull
PLAYER_FIELDS = ("first_name", "last_name", "position", "injury_status", "team", "number")

_session = requests.Session()  # one connection reused for every call instead of a new handshake each time
_response_cache = {}           # url -> (time to drop it, json)
_players_cache = {"date": None, "data": None}
_players_lock = threading.Lock()  # so two people loading at once don't both pull (and both write) the player file
_projection_cache = {}         # (league_id, week) -> (time pulled, {player_id: projected points})
PROJECTION_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")
IDP_POSITIONS = ("DL", "LB", "DB")

# --- how a league's roster slots (the roster_positions list sleeper gives for a league) are read ---
FLEX_SLOTS = {"FLEX", "SUPER_FLEX", "REC_FLEX", "WRRB_FLEX", "IDP_FLEX"}  # slots more than one position can fill
BENCH_SLOTS = {"BN", "IR", "TAXI"}
POSITION_SLOT = {"DE": "DL", "DT": "DL", "NT": "DL", "OLB": "LB", "ILB": "LB",
                 "CB": "DB", "S": "DB", "SS": "DB", "FS": "DB"}  # player positions that fill a differently named slot
# how much a player's remaining points are assumed to swing, see Player.projection_std
STD_BASE = 4.0
STD_PER_POINT = 0.4

DEFAULT_ROSTER_POSITIONS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"]  # used if a league doesn't list its slots


def main():
    # league_id = '1180303931006689280'  # FFF league
    # username = 'TitsBon'
    # week = 3

    # my_lineup, opp_lineup = pull_lineup(league_id, username, week)
    # print(my_lineup)
    # print(opp_lineup)

    pickem_league_id = '1265370587102973952'
    pull_picks(pickem_league_id, 'abonacci')


def _get(url, ttl=0):
    """
    GETs a sleeper endpoint and returns the json. If ttl is passed, the response is kept in memory and
    reused for that many seconds, so the things that don't change during a game aren't re-pulled every refresh.
    """
    now = time.time()
    cached = _response_cache.get(url)
    if ttl and cached and cached[0] > now:
        return cached[1]
    resp = _session.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if ttl:
        for old_url in [u for u, (expires, _) in _response_cache.items() if expires <= now]:
            _response_cache.pop(old_url, None)  # so the cache doesn't grow forever
        _response_cache[url] = (now + ttl, data)
    return data


def current_nfl_season():
    """The NFL season going on right now, e.g. 2026."""
    try:
        return int(_get(f'{API}/state/nfl', ttl=STATIC_TTL)['season'])
    except (requests.RequestException, ValueError, KeyError, TypeError):
        now = datetime.now()
        return now.year if now.month >= 3 else now.year - 1

def league_season(league_id):
    """The season (e.g. 2026) a league belongs to. Falls back to the current NFL season if the league can't be read."""
    try:
        return int(_get(f'{API}/league/{league_id}', ttl=STATIC_TTL)['season'])
    except (requests.RequestException, ValueError, KeyError, TypeError):
        pass
    return current_nfl_season()

def current_nfl_week():
    """The week sleeper says the NFL season is in right now (1 if it can't be reached)."""
    try:
        return min(18, max(1, int(_get(f'{API}/state/nfl', ttl=STATIC_TTL)['week'])))
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return 1

def pull_lineup(league_id, username, week, roster='both'):
    """
    This function calls the sleeper api and obtains the roster data. It has the functionality
    to do this for both the user and the user's opponent.

    Only the matchup endpoint is hit on every call (it is the only one with live points). The rosters,
    users and player metadata are cached.

    Parameters:
        - league_id (str): This is a string of the league id, a long set of numbers. Ours is 1180303931006689280
        - username (str): This is the user's username in sleeper
        - week(int): Week number of interest.
        - roster (str): This can be 'both', 'user', or 'opponent', and it just dictates which rosters to return.
        roster='both' is default.

    Returns:
        - player_data (Lineup): This is a simple class that houses the lineup (which is defined below).
        Doing this instead of their dict because they have a ton of  stuff we won't need so transferring
        everything would be inefficient.
        If roster='both' is passed, two of these vectors are returned, the first one for the user's team, the
        second one for the opponent's team. If there is no opponent that week, the opponent Lineup is empty.
    """
    if not (roster == "both" or roster == "user" or roster == "opponent"):
        raise ValueError("Error: Roster must be either 'both', 'user', or 'opponent'.")

    matchup_data, roster_ids, build_lineup, roster_positions = _league_week(league_id, week)

    user_data = _get(f'{API}/user/{username}', ttl=STATIC_TTL)
    if not user_data:
        raise ValueError(f"Sleeper user '{username}' was not found.")

    # --- Find your roster_id (different from owner_id!) ---
    my_roster_id = roster_ids.get(user_data['user_id'])
    if my_roster_id is None:
        raise ValueError(f"{username} does not have a team in league {league_id}.")

    user_matchup = next((m for m in matchup_data if m['roster_id'] == my_roster_id), None)
    if user_matchup is None:
        raise ValueError(f"No matchup found for {username} in week {week}.")

    if roster == "user":
        return build_lineup(user_matchup, username)

    # opponent is whoever else shares the same matchup_id (None on a bye / when eliminated)
    my_mid = user_matchup.get("matchup_id")
    opponent_matchup = next((m for m in matchup_data
                             if my_mid is not None and m.get("matchup_id") == my_mid and m["roster_id"] != my_roster_id),
                            None)
    opponent_lineup = build_lineup(opponent_matchup) if opponent_matchup else Lineup([], "---", "No opponent", roster_positions)

    if roster == "opponent":
        return opponent_lineup
    return build_lineup(user_matchup, username), opponent_lineup

def pull_league_lineups(league_id, week):
    """
    Returns the Lineup of every team in the league for the week, which is what the league median is worked out
    from. It uses the same pulls as pull_lineup, so calling both costs nothing extra.
    """
    matchup_data, _, build_lineup, _ = _league_week(league_id, week)
    return [build_lineup(matchup) for matchup in matchup_data if matchup.get('starters')]

def _league_week(league_id, week):
    """
    Pulls everything needed to build lineups for a week of a league. Only the matchup endpoint has live points,
    the rest is league info that is static during a slate.
    Returns (the week's matchup entries, {owner's user_id: roster_id}, a function that turns a matchup entry
    into a Lineup, the league's roster slots).
    """
    try:
        rosters = _get(f'{API}/league/{league_id}/rosters', ttl=STATIC_TTL)
    except requests.HTTPError:
        rosters = None  # sleeper answers 404 for a league id that doesn't exist
    if not rosters:
        raise ValueError(f"Sleeper league '{league_id}' was not found.")
    roster_positions = (_get(f'{API}/league/{league_id}', ttl=STATIC_TTL) or {}).get('roster_positions')
    users = {u['user_id']: u for u in _get(f'{API}/league/{league_id}/users', ttl=STATIC_TTL)}
    owner_by_roster = {r['roster_id']: r['owner_id'] for r in rosters}

    players_data = get_player_metadata()
    projections = get_projections(league_id, week)
    stats, scoring = get_stats(league_id, week)

    # --- Matchup info for given week (live points) ---
    matchup_data = _get(f'{API}/league/{league_id}/matchups/{week}', ttl=LIVE_TTL) or []

    def build_lineup(matchup, display_name=None):
        info = users.get(owner_by_roster.get(matchup['roster_id']), {})
        name = display_name or info.get('display_name', info.get('username', '---'))
        team_name = (info.get('metadata') or {}).get('team_name') or info.get('display_name', name)
        return Lineup(build_players(matchup, players_data, projections, stats, scoring), name, team_name, roster_positions)

    roster_ids = {owner: roster_id for roster_id, owner in owner_by_roster.items()}
    return matchup_data, roster_ids, build_lineup, roster_positions

def _stat_positions(league):
    """Positions to ask sleeper for. The defensive players are only pulled for leagues that start them."""
    positions = PROJECTION_POSITIONS
    if any(slot in IDP_POSITIONS or slot == "IDP_FLEX" for slot in league.get('roster_positions') or []):
        positions += IDP_POSITIONS
    return '&'.join(f'position[]={pos}' for pos in positions)

def get_projections(league_id, week):
    """
    Returns a dictionary of player_id -> projected fantasy points for the week, scored with this league's
    scoring settings. These are sleeper's full-game projections (the same stat lines the app uses).
    This endpoint isn't in sleeper's public docs, so if it ever fails we just return no projections
    rather than taking the dashboard down. Refreshed at most once per STATIC_TTL.
    """
    cached = _projection_cache.get((league_id, week))
    if cached and time.time() - cached[0] < STATIC_TTL:
        return cached[1]
    for old_key in [k for k, (pulled, _) in _projection_cache.items() if time.time() - pulled >= STATIC_TTL]:
        _projection_cache.pop(old_key, None)  # so the cache doesn't grow forever
    try:
        league = _get(f'{API}/league/{league_id}', ttl=STATIC_TTL)
        scoring = league.get('scoring_settings') or {}
        positions = _stat_positions(league)
        raw = _get(f'https://api.sleeper.app/projections/nfl/{league["season"]}/{week}?season_type=regular&{positions}')
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        print(f"Warning: could not pull projections: {e}")
        return {}

    projections = {}
    for entry in raw:
        stats = entry.get('stats') or {}
        projections[entry['player_id']] = sum(stats.get(stat, 0) * value for stat, value in scoring.items())
    _projection_cache[(league_id, week)] = (time.time(), projections)
    return projections

def get_stats(league_id, week):
    """
    Returns ({player_id: {stat: value}}, the league's scoring settings) for the week, which is what a player's
    points are made of. Like the projections this endpoint isn't in sleeper's public docs, so a failure just
    means no breakdowns. The stats are live, so they are only reused for a few seconds (the pull is the same
    for every league, so everyone looking at the dashboard shares it).
    """
    try:
        league = _get(f'{API}/league/{league_id}', ttl=STATIC_TTL)
        positions = _stat_positions(league)
        raw = _get(f'https://api.sleeper.app/stats/nfl/{league["season"]}/{week}?season_type=regular&{positions}', ttl=LIVE_TTL)
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        print(f"Warning: could not pull stats: {e}")
        return {}, {}
    return {entry['player_id']: entry.get('stats') or {} for entry in raw}, league.get('scoring_settings') or {}

def build_players(roster, players_data, projections=None, stats=None, scoring=None):
    """
    Given a matchup entry, it creates a list of Player objects for the starters
    """
    projections = projections or {}
    stats = stats or {}
    scoring = scoring or {}
    points = roster.get('players_points') or {}
    players = []
    for player in roster.get('starters') or []:  # list of player IDs
        data = players_data.get(player)
        if data is None:
            # empty starting slot
            players.append(Player("---", "---", "None", "None", 0, "--", 0))
            continue
        # make espn and sleeper agree
        team = 'WSH' if data.get("team") == 'WAS' else (data.get("team") or "--")
        players.append(Player(data.get("first_name") or "",
                              data.get("last_name") or "",
                              data.get("position") or "None",
                              data.get("injury_status"),
                              points.get(player) or 0,
                              team,
                              data.get("number"),
                              projections.get(player) or 0))
        # every stat that scored (or cost) them something: (stat, amount, points per, points)
        player_stats = stats.get(player) or {}
        players[-1].breakdown = [(stat, player_stats[stat], per, player_stats[stat] * per)
                                 for stat, per in scoring.items() if per and player_stats.get(stat)]
    return players

def pull_player_metadata(json_file, datefile):
    """
    - This pulls all of the player metadata for each player when needed. Sleeper says
    "it is intended only to be used once per day at most to keep your player IDs updated.
    The average size of this query is 5MB."
    - When calling this function, it will pull everything then save it to the JSON. Only the fields
    in PLAYER_FIELDS are saved, which keeps the file ~20x smaller and much faster to load.
    - It will also log the date in which it was pulled in datefile.
    """
    print("PULLING FROM SLEEPER")
    # --- Player metadata ---
    players_data = _get(f'{API}/players/nfl')
    players_data = {pid: {field: p.get(field) for field in PLAYER_FIELDS} for pid, p in players_data.items()}

    # written to a temporary file and swapped in, so a crash part way through can't leave a broken file behind
    with open(json_file + '.tmp', 'w') as f:
        json.dump(players_data, f)
    os.replace(json_file + '.tmp', json_file)

    # Get the current date and time to log it
    current_datetime = datetime.now()
    formatted_datetime = current_datetime.strftime("%Y-%m-%d")  # YYYY-MM-DD

    with open(datefile, 'w') as file:
        file.write(f"{formatted_datetime}")

def get_player_metadata(json_file='players_data.json', datefile='last_pull.txt'):
    """
    This returns all of the player metadata. If the datefile shows that the last date pulled was not
    today, we will pull the updated player metadata. If we are already updated, it will just return.
    The parsed file is kept in memory for the rest of the day so it is only read from disk once.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    if _players_cache["date"] == today:
        return _players_cache["data"]

    with _players_lock:
        if _players_cache["date"] == today:  # someone else loaded it while we waited for the lock
            return _players_cache["data"]

        try:
            with open(datefile, "r") as file:
                date_last_pulled = file.readline().strip()
        except FileNotFoundError:
            print(f"Warning: The file '{datefile}' was not found. Defaulting to None.")
            date_last_pulled = "none"

        # check the current date against when we last pulled
        if today != date_last_pulled or not os.path.exists(json_file):
            # if we pulled more than a day ago, pull it to update (or if the json just doesn't exist)
            pull_player_metadata(json_file, datefile)

        try:
            with open(json_file, 'r') as f:
                data = json.load(f)
        except ValueError:
            # the saved file is unreadable, so get a fresh one
            pull_player_metadata(json_file, datefile)
            with open(json_file, 'r') as f:
                data = json.load(f)

        _players_cache["date"] = today
        _players_cache["data"] = data
        return data


class Player:
    """
    This class houses all of the information that we actually care about for a player. This object is returned
    for each player in vector format in pull_lineup(). Note that the variable names are exactly the same as the
    unique keys in the dictionary for a player from the Sleeper API. They should be pretty self explainatory.
    """
    def __init__(self, first_name, last_name, position, injury_status, player_points, team, number, projected=0):
        self.first_name = first_name
        self.last_name = last_name
        self.position = position
        self.injury_status = injury_status
        self.player_points = player_points
        self.team = team
        self.number = number
        self.game_status = None
        self.game_state = None   # 'pre', 'in', 'post' or 'bye'
        self.game_detail = None  # clock / kickoff time text
        self.game_remaining = 1.0  # fraction of their game still to be played
        self.projected = projected  # full-game projection from before kickoff
        self.breakdown = []  # scoring breakdown, a list of (stat, amount, points per, points)
        self.possession = None

    @property
    def live_projection(self):
        """Where they are projected to finish: what they have, plus their projection for the time that is left."""
        return self.player_points + self.projected * self.game_remaining

    @property
    def projection_std(self):
        """
        Rough standard deviation of the points still to come, used for the win probability estimate. A player
        projected for 20 swings by about 12 over a full game, one projected for 8 by about 7, and it shrinks
        as their game runs out. These are deliberately on the wide side: fantasy scores are streaky (one long
        touchdown is 10+ points) and teammates' scores move together, which a simple model like this would
        otherwise ignore and come out overconfident. Raise STD_BASE / STD_PER_POINT for even less certainty.
        """
        if self.projected <= 0:
            return 0.0
        return (STD_BASE + STD_PER_POINT * self.projected) * self.game_remaining ** 0.5

    def __str__(self):
        return f'{self.team} {self.position} - {self.first_name} {self.last_name}: {self.player_points} pts.'

    def __repr__(self):
        return str(self)

class Lineup:
    """
    This is a full lineup, which consists of a list of players, the team name, the user associated with that
    team, the amount of total points the team has accrued, etc.
    """
    def __init__(self, player_list, username, team_name, roster_positions=None):
        self.player_list = player_list
        self.username = username
        self.team_name = team_name
        self.roster_positions = roster_positions or DEFAULT_ROSTER_POSITIONS  # the league's slots, in sleeper's order
        self.total_points = self.calc_total_points()

    def calc_total_points(self):
        return sum((player.player_points for player in self.player_list), 0.0)

    @property
    def projected_points(self):
        """Projected final score. Call assign_game_status first so finished games stop counting."""
        return sum((player.live_projection for player in self.player_list), 0.0)

    def order_list(self):
        """
        This orders the player list by position and then by points, following the league's own roster slots
        so it works for any format (superflex, kickers, defenses, IDP...).
        The top scorers at each position fill that position's starting slots (a league with two RB slots gets
        its top two RBs, and so on, in the order the league lists them). Everyone left over is playing a flex
        spot, and they go where the league's first flex slot is, best first. Empty slots go at the end.
        """
        by_points = sorted(self.player_list, key=lambda p: p.player_points, reverse=True)

        # how many dedicated slots each position has, e.g. {"QB": 1, "RB": 2, "WR": 2, "TE": 1}
        slot_counts = {}
        slots_before_flex = None
        for slot in self.roster_positions:
            if slot in FLEX_SLOTS:
                if slots_before_flex is None:
                    slots_before_flex = len(slot_counts)
            elif slot not in BENCH_SLOTS:
                slot_counts[slot] = slot_counts.get(slot, 0) + 1

        starters = []  # one list of players per position
        flexlist = []
        for slot, count in slot_counts.items():
            players = [p for p in by_points if POSITION_SLOT.get(p.position, p.position) == slot]
            starters.append(players[:count])
            flexlist.extend(players[count:])
        flexlist.extend(p for p in by_points
                        if POSITION_SLOT.get(p.position, p.position) not in slot_counts and p.position != "None")
        flexlist.sort(key=lambda p: p.player_points, reverse=True)
        empty_slots = [p for p in by_points if p.position == "None"]

        if slots_before_flex is None:
            slots_before_flex = len(starters)
        before = [p for players in starters[:slots_before_flex] for p in players]
        after = [p for players in starters[slots_before_flex:] for p in players]
        self.player_list = before + flexlist + after + empty_slots

    def assign_game_status(self, games):
        """
        Given a list of game dictionaries (each with home_team, away_team, status, etc),
        updates each player's game fields and .possession based on their team's current game.
        """
        # Precompute lookup table for O(1) access
        team_to_game = {}
        for g in games:
            team_to_game[g["home_team"]] = g
            team_to_game[g["away_team"]] = g

        for player in self.player_list:
            game = team_to_game.get(player.team)
            if game:
                player.game_status = game["status"]
                player.game_state = game["state"]
                player.game_detail = game["detail"]
                player.game_remaining = game["remaining"]
                player.possession = game['possession'] == player.team
            else:
                player.game_status = "BYE"
                player.game_state = "bye"
                player.game_detail = "BYE"
                player.game_remaining = 0.0
                player.possession = None


    def get_players_by_pos(self, pos):
        players = []
        for player in self.player_list:
            if player.position == pos:
                players.append(player)
        return players

    def __str__(self):
        string = f"{self.team_name} ({self.username}) - {self.total_points:.2f} Total Points:\n"
        for player in self.player_list:
            string += f'{str(player)}\n'
        return string

    def __repr__(self):
        return str(self)


#################################
# This is now for the pickem pool
#################################

def pull_picks(league_id, username):
    """
    This should pull a list of all of your picks and what you need from the pickem pool
    """

    url_user = f'https://api.sleeper.app/v1/user/{username}'
    user_data = requests.get(url_user).json()
    user_id = user_data['user_id']
    users = requests.get(f"https://api.sleeper.app/v1/league/{league_id}/users").json()

    user = next(u for u in users if u["user_id"] == user_id)
    print(user)
    # Sleeper's API doesn't include pickem pools yet, but hidden endpoints may exist... must check



if __name__ == "__main__":
    main()
