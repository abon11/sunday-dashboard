import pandas as pd
import requests
import json
from datetime import datetime
import os

def main():
    # league_id = '1180303931006689280'  # FFF league
    # username = 'TitsBon'
    # week = 3

    # my_lineup, opp_lineup = pull_lineup(league_id, username, week)
    # print(my_lineup)
    # print(opp_lineup)

    pickem_league_id = '1265370587102973952'
    pull_picks(pickem_league_id, 'abonacci')


def pull_lineup(league_id, username, week, roster='both'):
    """
    This function calls the sleeper api and obtains the roster data. It has the functionality
    to do this for both the user and the user's opponent.
    This is kinda gross i wanna make it cleaner

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
    user_teamname = next(u["metadata"].get("team_name", u["display_name"]) for u in requests.get(f"https://api.sleeper.app/v1/league/{league_id}/users").json() if u["user_id"] == user_id)


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
        player_list = build_players(user_roster, players_data)
        return Lineup(player_list, username, user_teamname)
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

        # Get opponent teamname
        opp_owner_id = next(r['owner_id'] for r in data if r['roster_id'] == opponent_roster['roster_id'])
        # get all league users (you can move this above and reuse)
        users = requests.get(f'https://api.sleeper.app/v1/league/{league_id}/users').json()
        opponent_info = next(u for u in users if u['user_id'] == opp_owner_id)
        opponent_teamname = opponent_info['metadata'].get('team_name', opponent_info.get('display_name'))
        opponent_username = opponent_info.get('display_name', opponent_info.get('username'))

        if roster == "opponent":
            player_list =  build_players(opponent_roster, players_data)
            return Lineup(player_list, opponent_username, opponent_teamname)
        else:
            return Lineup(build_players(user_roster, players_data), username, user_teamname), Lineup(build_players(opponent_roster, players_data), opponent_username, opponent_teamname)

def build_players(roster, players_data):
    """
    Given a list of player ids, it creates a list of Player objects initiated with no points
    """
    starter_ids = roster['starters']    # list of player IDs
    players = []
    for player in starter_ids:
        try:
            players.append(Player(players_data[player]["first_name"], 
                                players_data[player]["last_name"], 
                                players_data[player]["position"],
                                players_data[player]["injury_status"],
                                roster.get('players_points', {})[player],
                                players_data[player]["team"],
                                players_data[player]["number"]))
        except KeyError:
            players.append(Player("---", "---", "None", "None", 0, "--", 0))
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
    """
    This class houses all of the information that we actually care about for a player. This object is returned
    for each player in vector format in pull_lineup(). Note that the variable names are exactly the same as the 
    unique keys in the dictionary for a player from the Sleeper API. They should be pretty self explainatory.
    """
    def __init__(self, first_name, last_name, position, injury_status, player_points, team, number):
        self.first_name = first_name
        self.last_name = last_name
        self.position = position
        self.injury_status = injury_status
        self.player_points = player_points
        self.team = team
        self.number = number

    def __str__(self):
        return f'{self.team} {self.position} - {self.first_name} {self.last_name}: {self.player_points} pts.'
    
    def __repr__(self):
        return str(self)

class Lineup:
    """
    This is a full lineup, which consists of a list of players, the team name, the user associated with that
    team, the amount of total points the team has accrued, etc.
    """
    def __init__(self, player_list, username, team_name):
        self.player_list = player_list
        self.username = username
        self.team_name = team_name
        self.total_points = self.calc_total_points()

    def calc_total_points(self):
        pts = 0.0
        for player in self.player_list:
            pts += player.player_points
        return pts
    
    def order_list(self, pos_ordering=["QB", "RB", "WR", "TE", "FLX"]):
        """
        This orders the player list by position and then by points
        """
        def bubble_sort_players(arr):
            n = len(arr)
            for i in range(n - 1):
                for j in range(0, n - i - 1):
                    if arr[j].player_points < arr[j + 1].player_points:  # Compare and swap for descending order
                        arr[j], arr[j + 1] = arr[j + 1], arr[j]
            return arr
        
        newlist = []
        flexlist = []

        for pos in pos_ordering:
            if pos != "FLX":
                players = self.get_players_by_pos(pos)
                sorted = bubble_sort_players(players)
                newlist.append(sorted.pop(0))
                if (pos == "RB" or pos == "WR"):
                    newlist.append(sorted.pop(0))
                if len(sorted) > 0:
                    flexlist.extend(sorted)
            else:
                sorted_flex = bubble_sort_players(flexlist)
                newlist.extend(sorted_flex)
                newlist.extend(self.get_players_by_pos("None"))  # add potential None players to the end
        self.player_list = newlist



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