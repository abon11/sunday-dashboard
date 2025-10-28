"""
This houses all of the code to pull the live nfl game data from espn
Technically this is unofficial... if we were to commericalize I think we'd have to use something else
"""
import requests

def main():
    # games = pull_games(3)
    # print(games)
    pull_lines()

def pull_games(week):
    url = f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?week={week}"
    data = requests.get(url).json()
    games = []
    for e in data["events"]:
        comp = e["competitions"][0]
        home = comp["competitors"][0]
        away = comp["competitors"][1]
        games.append({
            "home_team": home["team"]["abbreviation"],
            "away_team": away["team"]["abbreviation"],
            "home_score": int(home["score"]),
            "away_score": int(away["score"]),
            "status": comp["status"]["type"]["description"],
            "quarter": comp["status"]["period"],
            "clock": comp["status"].get("displayClock", "")
        })
    return games

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