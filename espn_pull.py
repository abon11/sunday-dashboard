"""
This houses all of the code to pull the live nfl game data from espn
Technically this is unofficial... if we were to commericalize I think we'd have to use something else
"""
import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

_session = requests.Session()  # reuse one connection across refreshes

def main():
    # games = pull_games(3)
    # print(games)
    pull_lines()

def pull_games(week):
    url = f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?week={week}"
    resp = _session.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    games = []
    for e in data["events"]:
        comp = e["competitions"][0]
        home = comp["competitors"][0]
        away = comp["competitors"][1]
        # Default possession = None (for Scheduled/Final games)
        possession = None
        if "situation" in comp and comp["situation"]:
            possession_id = comp["situation"].get("possession")
            if possession_id == home["id"]:
                possession = home["team"]["abbreviation"]
            elif possession_id == away["id"]:
                possession = away["team"]["abbreviation"]

        status_type = comp["status"]["type"]
        state = status_type.get("state", "pre")  # 'pre', 'in' or 'post'
        if state == "pre":
            detail = kickoff_label(e.get("date"))
        else:
            detail = status_type.get("shortDetail") or status_type["description"]  # e.g. '5:32 - 3rd', 'Halftime', 'Final/OT'

        games.append({
            "id": e["id"],
            "remaining": fraction_remaining(state, comp["status"]["period"], comp["status"].get("clock")),
            "home_team": home["team"]["abbreviation"],
            "away_team": away["team"]["abbreviation"],
            "home_score": int(home["score"]),
            "away_score": int(away["score"]),
            "status": status_type["description"],
            "state": state,
            "detail": detail,
            "quarter": comp["status"]["period"],
            "clock": comp["status"].get("displayClock", ""),
            "possession": possession,  # <-- new field
        })
    return games

def fraction_remaining(state, quarter, clock_seconds):
    """Fraction of regulation still to be played (1 before kickoff, 0.5 at the half, 0 once final or in OT)."""
    if state == "pre":
        return 1.0
    if state != "in" or quarter > 4:
        return 0.0
    return min(1.0, ((4 - quarter) * 900 + (clock_seconds or 0)) / 3600)

def pull_live_spreads(games):
    """
    Returns a dictionary of team -> current live point spread (e.g. {'GB': -11.5, 'CHI': 11.5}) for the games
    that are in progress. Only espn's per-game odds endpoint carries the in-game line, so it is one request
    per live game, done in parallel. A game is left out if there is no live line posted for it right now.
    """
    live_games = [g for g in games if g["state"] == "in"]
    if not live_games:
        return {}

    def pull_one(game):
        url = (f"https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/events/{game['id']}"
               f"/competitions/{game['id']}/odds")
        try:
            resp = _session.get(url, timeout=5)
            resp.raise_for_status()
            items = resp.json().get("items", [])
        except (requests.RequestException, ValueError):
            return {}
        # each sportsbook is listed twice: the closing line, and a "... - Live Odds" entry that moves in game
        for item in items:
            if "live" not in item.get("provider", {}).get("name", "").lower():
                continue
            spreads = {}
            for side, team in (("awayTeamOdds", game["away_team"]), ("homeTeamOdds", game["home_team"])):
                text = ((item.get(side) or {}).get("current") or {}).get("pointSpread", {}).get("american")
                try:
                    spreads[team] = 0.0 if text in ("EVEN", "PK") else float(text)
                except (TypeError, ValueError):
                    return {}
            return spreads
        return {}

    spreads = {}
    with ThreadPoolExecutor(max_workers=len(live_games)) as pool:
        for result in pool.map(pull_one, live_games):
            spreads.update(result)
    return spreads

def kickoff_label(iso_date):
    """Turns espn's UTC kickoff time into local time text like 'Sun 1:00 PM'."""
    try:
        kickoff = datetime.fromisoformat(iso_date.replace("Z", "+00:00")).astimezone()
        return kickoff.strftime("%a %-I:%M %p")
    except (AttributeError, ValueError):
        return "TBD"

def pull_lines():
    resp = requests.get("https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard")
    data = resp.json()

    for event in data["events"]:
        print(event)
        comp = event["competitions"][0]
        if "odds" in comp:
            odds = comp["odds"][0]
            home = comp["competitors"][0]["team"]["abbreviation"]
            away = comp["competitors"][1]["team"]["abbreviation"]
            print(home, away, odds["details"])

if __name__ == "__main__":
    main()
