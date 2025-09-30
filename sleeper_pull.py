import pandas as pd
import requests

league_id = '1180303931006689280'

# --- Get all rosters in league ---
url_rosters = f'https://api.sleeper.app/v1/league/{league_id}/rosters'
data = requests.get(url_rosters).json()

# --- Get your user_id ---
username = 'mjthekid'
url_user = f'https://api.sleeper.app/v1/user/{username}'
user_data = requests.get(url_user).json()
user_id = user_data['user_id']

# --- Find your roster_id (different from owner_id!) ---
my_roster = next(roster for roster in data if roster['owner_id'] == user_id)
my_roster_id = my_roster['roster_id']
my_player_ids = my_roster['players']

# --- Player metadata ---
url_players = 'https://api.sleeper.app/v1/players/nfl'
players_data = requests.get(url_players).json()

# --- Matchup info for given week ---
week = 4
url_matchups = f'https://api.sleeper.app/v1/league/{league_id}/matchups/{week}'
matchup_data = requests.get(url_matchups).json()

# Find your matchup entry
my_matchup = next(matchup for matchup in matchup_data if matchup['roster_id'] == my_roster_id)

# --- Extract starters & points ---
my_starters = my_matchup['starters']    # list of player IDs
my_points = my_matchup['points']        # actual fantasy points
my_proj = my_matchup

print(f"My Team ({my_matchup.get("points")} pts):")
for starter in my_starters:
    print(f'{players_data[starter]["position"]} - {players_data[starter]["first_name"]} {players_data[starter]["last_name"]}: {my_matchup.get('players_points', {})[starter]} pts.')

# --- Now get the opposing team's roster ---
my_mid = my_matchup.get("matchup_id")
# find all rosters sharing the same matchup_id (handles doubleheaders / 3+ team formats too)
same_mid = [m for m in matchup_data if m.get("matchup_id") == my_mid]
# opponent entries are everyone in same_mid except me
opponents = [m for m in same_mid if m["roster_id"] != my_roster_id]
# usually head-to-head => one opponent; use the first if so
opponent_matchup = opponents[0] if opponents else None

opponent_starters = opponent_matchup['starters']
print(f"\nOpponent's Team ({opponent_matchup.get("points")} pts):")
for starter in opponent_starters:
    print(f'{players_data[starter]["position"]} - {players_data[starter]["first_name"]} {players_data[starter]["last_name"]}: {opponent_matchup.get('players_points', {})[starter]} pts.')