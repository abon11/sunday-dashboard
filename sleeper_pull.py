import pandas as pd
import requests
import json
from datetime import datetime
import os

def main():
    league_id = '1180303931006689280'
    username = 'TitsBon'
    week = 5

    my_roster, opp_roster = pull_team(league_id, username, week)
    print("My roster:")
    for p in my_roster:
        p.print_player()
    print("\nOpponent's roster:")
    for p in opp_roster:
        p.print_player()


def pull_team(league_id, username, week, roster='both'):
    """
    This function calls the sleeper api and obtains the roster data. It has the functionality
    to do this for both the user and the user's opponent.

    Parameters:
        - league_id (str): This is a string of the league id, a long set of numbers. Ours is 1180303931006689280
        - username (str): This is the user's username in sleeper
        - week(int): Week number of interest. 
        - roster (str): This can be 'both', 'user', or 'opponent', and it just dictates which rosters to return.
        roster='both' is default.

    Returns:
        - player_data (np.array[Player]): This is a simple vector that houses a bunch of Player objects, one for
        each player on the team you are requesting. Doing this instead of their dict because they have a ton of 
        stuff we won't need so transferring everything would be inefficient. Not using a custom dict in the weird
        scenario of two players having the same name (don't wanna give each player unique keys that seems like a 
        headache). A simple vector of the starting lineup should work fine. 
        If roster='both' is passed, two of these vectors are returned, the first one for the user's team, the 
        second one for the opponent's team.
    """
    if not (roster == "both" or roster == "user" or roster == "opponent"):
        raise ValueError("Error: Roster must be either 'both', 'user', or 'opponent'.")

    # --- Get all rosters in league ---
    url_rosters = f'https://api.sleeper.app/v1/league/{league_id}/rosters'
    data = requests.get(url_rosters).json()

    # --- Get your user_id ---
    url_user = f'https://api.sleeper.app/v1/user/{username}'
    user_data = requests.get(url_user).json()
    user_id = user_data['user_id']

    # --- Find your roster_id (different from owner_id!) ---
    my_roster = next(roster for roster in data if roster['owner_id'] == user_id)
    my_roster_id = my_roster['roster_id']
    my_player_ids = my_roster['players']

    # --- Player metadata ---
    players_data = get_player_metadata()

    # --- Matchup info for given week ---
    url_matchups = f'https://api.sleeper.app/v1/league/{league_id}/matchups/{week}'
    matchup_data = requests.get(url_matchups).json()

    # Find your matchup entry
    user_roster = next(matchup for matchup in matchup_data if matchup['roster_id'] == my_roster_id)
    # get the starters on the user team

    if roster == "user":
        return build_players(user_roster, players_data)
    else:
        # if it isn't just the user, we must get the other starters as well
        # --- Now get the opposing team's roster ---
        my_mid = user_roster.get("matchup_id")
        # find all rosters sharing the same matchup_id (handles doubleheaders / 3+ team formats too)
        same_mid = [m for m in matchup_data if m.get("matchup_id") == my_mid]
        # opponent entries are everyone in same_mid except me
        opponents = [m for m in same_mid if m["roster_id"] != my_roster_id]
        # usually head-to-head => one opponent; use the first if so
        opponent_roster = opponents[0] if opponents else None

        if roster == "opponent":
            return build_players(opponent_roster, players_data)
        else:
            return build_players(user_roster, players_data), build_players(opponent_roster, players_data)

def build_players(roster, players_data):
    """
    Given a list of player ids, it creates a list of Player objects initiated with no points
    """
    starter_ids = roster['starters']    # list of player IDs
    players = []
    for player in starter_ids:
        players.append(Player(players_data[player]["first_name"], 
                              players_data[player]["last_name"], 
                              players_data[player]["position"],
                              players_data[player]["injury_status"],
                              roster.get('players_points', {})[player],
                              players_data[player]["team"],
                              players_data[player]["number"]))
    return players

def pull_player_metadata(json_file, datefile):
    """
    - This pulls all of the player metadata for each player when needed. Sleeper says 
    "it is intended only to be used once per day at most to keep your player IDs updated. 
    The average size of this query is 5MB." 
    - When calling this function, it will pull everything then save it to the JSON.
    - It will also log the date in which it was pulled in datefile.
    """
    print("PULLING FROM SLEEPER")
    # --- Player metadata ---
    url_players = 'https://api.sleeper.app/v1/players/nfl'
    players_data = requests.get(url_players).json()

    with open(json_file, 'w') as f:
        json.dump(players_data, f, indent=4)

    # Get the current date and time to log it
    current_datetime = datetime.now()
    formatted_datetime = current_datetime.strftime("%Y-%m-%d")  # YYYY-MM-DD

    with open(datefile, 'w') as file:
        file.write(f"{formatted_datetime}")

def get_player_metadata(json_file='players_data.json', datefile='last_pull.txt'):
    """
    This returns all of the player metadata. If the datefile shows that the last date pulled was not
    today, we will pull the updated player metadata. If we are already updated, it will just return.
    """
    try:
        with open(datefile, "r") as file:
            date_last_pulled = file.readline().strip()
    except FileNotFoundError:
        print(f"Warning: The file '{datefile}' was not found. Defaulting to None.")
        date_last_pulled = "none"
    
    # check the current date against when we last pulled
    current_datetime = datetime.now()
    if current_datetime.strftime("%Y-%m-%d") != date_last_pulled or not os.path.exists(json_file):
        # if we pulled more than a day ago, pull it to update (or if the json just doesn't exist)
        pull_player_metadata(json_file, datefile)

    # then update and return
    with open(json_file, 'r') as f:
        data = json.load(f)
    
    return data


class Player:
    def __init__(self, first_name, last_name, position, injury_status, player_points, team, number):
        """
        This class houses all of the information that we actually care about for a player. This object is returned
        for each player in vector format in pull_team(). Note that the variable names are exactly the same as the 
        unique keys in the dictionary for a player from the Sleeper API. They should be pretty self explainatory.
        """
        self.first_name = first_name
        self.last_name = last_name
        self.position = position
        self.injury_status = injury_status
        self.player_points = player_points
        self.team = team
        self.number = number

    def print_player(self):
        print(f'{self.team} {self.position} - {self.first_name} {self.last_name}: {self.player_points} pts.')


if __name__ == "__main__":
    main()