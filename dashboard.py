import streamlit as st
import pandas as pd
from sleeper_pull import pull_lineup
from espn_pull import pull_games
import matplotlib.colors as mcolors
from streamlit_extras.stylable_container import stylable_container
import os
import json
from datetime import datetime



def main():
    save_state_filename = 'save_state.json'
    league_id = "1180303931006689280"  # FFF league
    username = "TitsBon"
    if "selected_week" not in st.session_state:
        if not os.path.exists(save_state_filename):
            with open(save_state_filename, 'w') as f:
                json.dump(dict({'current_week': 1}), f, indent=4)
                st.session_state["selected_week"] = 1
        else:
            with open(save_state_filename, 'r') as f:
                save_state = json.load(f)
            st.session_state["selected_week"] = save_state["current_week"]
    # week = st.session_state["selected_week"]
    my_lineup, opp_lineup = pull_lineup(league_id, username, st.session_state["selected_week"])

    bet_file = f'bets/wk{st.session_state["selected_week"]}.json'

    st.session_state.bets = initialize_bet_dict(bet_file)

    # --- UI ---
    st.set_page_config(page_title="Football Sunday Dashboard", layout="wide")
    st.markdown(
        """
        <style>
            .block-container {padding-top: 1rem; padding-bottom: 1rem;}
            h1, h2, h3 {margin-top: 0rem; margin-bottom: 0.5rem;}
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("""
    <style>
    /* neutral reset only */
    div.stButton > button,
    div[data-testid="stButton"] > button,
    div[data-testid="stButton"] > div > button {
    margin: 0;
    padding: 0;
                
    min-height: 0 !important;
    padding: 0 !important;
    margin: -100 !important;
    
    button:hover {
        opacity: 0.1 !important;
    }
    }
    div[data-testid="stHorizontalBlock"] {
        margin-top: -14px !important;
        margin-bottom: -12px !important;
    }
    </style>
    """, unsafe_allow_html=True)

    params = st.query_params

    # A. Bet submission takes priority
    if "bet_team" in params and "spread" in params:
        team = params["bet_team"]
        try:
            val = float(params["spread"])
            spread = round(val * 2) / 2.0  # nearest 0.5
            print(f"Saved bet: {team} {spread:+.1f}")   # <-- prints to console
            st.session_state.bets[team] = (spread, datetime.now().timestamp())
            # save the bets for when refresh happens
            with open(bet_file, 'w') as f:
                json.dump(st.session_state.bets, f, indent=4)
        except ValueError:
            print(f"Bad spread for {team}: {params['spread']}")

        st.session_state.selected_team = None         # clear the bet UI
        st.query_params.clear()

    # B. Team selection (from clicking a team button)
    elif "select_team" in params:
        st.session_state.selected_team = params["select_team"]
        st.query_params.clear()
    
    if "clear_bets" in params:
        st.session_state.bets = initialize_bet_dict(bet_file, clear=True)
        st.query_params.clear()

    # --- Title and Menu ---
    top_left, top_right = st.columns([3, 1])
    with top_left:
        st.title(f"Football Sunday Dashboard - Week {st.session_state["selected_week"]}")
    with top_right:
        st.write("")
        st.write("")

        selected_week = st.selectbox(
            "Select Week",
            options=[f"Week {i}" for i in range(1, 19)],
            index=st.session_state["selected_week"] - 1,
            label_visibility="collapsed",
        )

        new_week = int(selected_week.split()[-1])

        if new_week != st.session_state["selected_week"]:
            with open(save_state_filename, 'r+') as f:
                save_state = json.load(f)
                save_state["current_week"] = new_week
                f.seek(0)              # move pointer to start of file
                json.dump(save_state, f, indent=4)
                f.truncate()
            st.session_state["selected_week"] = new_week
            st.rerun()

    # --- Layout Columns ---
    col1, col2, col3 = st.columns(3)
    with col1:
        show_lineup(my_lineup, opp_lineup)
    with col2:
        show_lineup(opp_lineup, my_lineup)
    with col3:
        show_games(st.session_state["selected_week"], st.session_state.bets)

    # --- Bet Entry Section directly below lineups ---
    with st.container():
        # Slightly overlap upward into lineup space
        st.markdown(
            """
            <div style='margin-top:-2rem;'></div>
            """,
            unsafe_allow_html=True,
        )

        bet_col1, _ = st.columns([2, 1])  # span under first two columns
        with bet_col1:
            show_bet_input_area()


# helper to render a Lineup
def show_lineup(lineup, other_lineup):
    st.subheader(f"{lineup.team_name} ({lineup.username})")
    st.metric("Total Points", f"{lineup.total_points:.2f}")
    # st.write("---")

    lineup.order_list()
    other_lineup.order_list()

    for p, op in zip(lineup.player_list, other_lineup.player_list):
        color = diff_color(p.player_points, op.player_points)
        text_color = "white" if p.player_points - op.player_points < 0 else "black"
        st.markdown(
            f"""
            <div style="
                background-color:{color};
                color:black;
                padding:10px 14px;
                margin-bottom:6px;
                border-radius:10px;
                font-weight:500;
            ">
                <b>{p.first_name} {p.last_name}</b> ({p.team} {p.position}) - {p.player_points:.1f} pts
            </div>
            """,
            unsafe_allow_html=True
        )

def diff_color(p_points, op_points):
    """
    Returns a hex color smoothly transitioning from red (down 10)
    to yellow (even) to green (up 10).
    """

    diff = max(-10, min(10, p_points - op_points))  # clamp between -10 and 10
    normalized = (diff + 10) / 20.0  # map [-10, 10] → [0, 1]

    # cmap = mcolors.LinearSegmentedColormap.from_list("perf", ["#F14B4B", "#F0F04B", "#50EE50"])  # red → yellow → green
    cmap = mcolors.LinearSegmentedColormap.from_list("perf", ["#F63737", "#DCDADA", "#33F333"])
    return mcolors.to_hex(cmap(normalized))

def show_games(week, bet_dict):
    st.subheader("Full Slate")
    games = pull_games(week)

    if "selected_team" not in st.session_state:
        st.session_state.selected_team = None
    if "bets" not in st.session_state:
        st.session_state.bets = {}

    team_colors = {
        "NYG": "#003C7E", "WSH": "#773141", "DAL": "#041E42", "PHI": "#004C54",
        "BUF": "#00338D", "MIA": "#008E97", "NYJ": "#125740", "NE": "#002244",
        "GB": "#203731", "MIN": "#4F2683", "DET": "#0076B6", "CHI": "#0B162A",
        "CIN": "#FB4F14", "CLE": "#311D00", "BAL": "#241773", "PIT": "#FFB612",
        "SF": "#AA0000", "LAR": "#003594", "SEA": "#002244", "ARI": "#97233F",
        "LV": "#000000", "DEN": "#FB4F14", "KC": "#E31837", "LAC": "#0080C6",
        "CAR": "#0085CA", "ATL": "#A71930", "NO": "#D3BC8D", "TB": "#D50A0A",
        "IND": "#002C5F", "TEN": "#4B92DB", "HOU": "#03202F", "JAX": "#006778",
    }

    for game in games:
        away_team = game["away_team"]; home_team = game["home_team"]
        away_color = team_colors.get(away_team, "#888"); home_color = team_colors.get(home_team, "#888")
        status = f"Q{game['quarter']} {game['clock']}" if game["status"] == "In Progress" else "TBD" if game["status"] == "Scheduled" else game["status"]
        away_score = f"{int(game['away_score']):>2}"; home_score = f"{int(game['home_score']):>2}"

        def construct_bet_string(team, spread):
            if spread == 0:
                string = f'{team}: ML'
            else:
                string = f'{team}: {spread:+.1f}'
            return string

        if bet_dict[away_team][0] is not None and bet_dict[home_team][0] is not None:
            # take the more recently placed bet (we could clear the other bet but unnecessary)
            if bet_dict[away_team][1] >= bet_dict[home_team][1]:
                bet_string = construct_bet_string(away_team, bet_dict[away_team][0])
            else:
                bet_string = construct_bet_string(home_team, bet_dict[home_team][0])
        elif bet_dict[away_team][0] is not None:
            bet_string = construct_bet_string(away_team, bet_dict[away_team][0])
        elif bet_dict[home_team][0] is not None:
            bet_string = construct_bet_string(home_team, bet_dict[home_team][0])
        else:
            bet_string = '---'

        params = st.query_params
        if "clicked_team" in params:
            clicked = params["clicked_team"]
            print(f"Clicked {clicked}")  # appears in terminal
            st.session_state.selected_team = clicked
            st.query_params.clear()  # reset after handling

        st.markdown(f"""
        <div style="
            background-color: #f8f8f8;
            border: 1px solid #ddd;
            border-radius: 2px;
            padding: 4px 4px;
            margin: 0px;            /* eliminates spacing */
        ">
        <div style="display:flex; align-items:center;">
            <div style="flex:0.4;">
                <form action="" method="get" style="margin:0;">
                <input type="hidden" name="select_team" value="{away_team}">
                    <button type="submit" style="
                        background-color:{away_color};
                        color:white;
                        border:2px solid black;
                        border-radius:6px;
                        font-weight:700;
                        width:3.8em;
                        height:2em;
                        cursor:pointer;
                    ">
                        {away_team}
                    </button>
                </form>
            </div>
            <div style="flex:0.8; text-align:center; font-family:monospace; font-weight:bold;">
            {away_score} - {home_score}
            </div>
            <div style="flex:0.4;">
                <form action="" method="get" style="margin:0;">
                <input type="hidden" name="select_team" value="{home_team}">
                    <button type="submit" style="
                        background-color:{home_color};
                        color:white;
                        border:2px solid black;
                        border-radius:6px;
                        font-weight:700;
                        width:3.8em;
                        height:2em;
                        cursor:pointer;
                    ">
                        {home_team}
                    </button>
                </form>
            </div>
            <div style="flex:2.0; font-family:monospace; margin-left:10px;">
            | {status} | {bet_string}
            </div>
        </div>
        </div>
        """, unsafe_allow_html=True)


def show_bet_input_area():
    team = st.session_state.get("selected_team")
    st.markdown("<hr style='margin-top:-57px; margin-bottom:4px;'>", unsafe_allow_html=True)

    if not team:
        # Move info box up and add "Clear Bets" button on right
        st.markdown("""
        <style>
        div[data-testid="stAlert"] {
            margin-top: -80px !important;
            width: 85% !important;       /* ✅ change width here */
            margin-left: 0px !important; /* optional: move slightly right */
        }
        </style>


        <div style="display:flex; align-items:center; justify-content:space-between; margin-right:12px; margin-top:-52px;">
            <div style="flex:1;">
                <div id="info-box"></div>
            </div>
            <div>
                <form action="" method="get" style="margin:0;">
                    <input type="hidden" name="clear_bets" value="1">
                    <button type="submit"
                        style="background-color:#FF4B4B; color:white; border:none;
                               border-radius:6px; height:32px; width:100px;
                               font-weight:600; cursor:pointer;">
                        Clear Bets
                    </button>
                </form>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Render info box in its proper place (fills the left side of flex)
        st.info("Click a team in the game list to start or edit a bet.")
        return

    st.markdown(f"""
    <div style="margin-left:6px; margin-top:-63px; font-weight:700; font-size:1.1em;">
        Enter the spread for the bet you placed on <span style="color:#0073e6;">{team}</span> (Moneyline=0):
    </div>
    <div style="margin-top:4px; margin-left:6px; display:flex; align-items:center;">
        <form action="" method="get" style="display:flex; align-items:center; gap:8px;">
            <input type="number" name="spread" step="0.5" required
                   style="width:90px;height:30px;font-size:14px;border-radius:6px;border:1px solid #bbb;text-align:center;">
            <input type="hidden" name="bet_team" value="{team}">
            <button type="submit"
                    style="background-color:#0073e6;color:white;border:none;border-radius:6px;height:32px;width:100px;font-weight:600;cursor:pointer;">
                Save Bet
            </button>
        </form>
    </div>
    """, unsafe_allow_html=True)


def initialize_bet_dict(bet_file, clear=False):
    os.makedirs(os.path.dirname(bet_file), exist_ok=True)
    if not os.path.exists(bet_file) or clear is True:
        # dictionary of a tuple where the first entry is the spread and the second is the datetime it was entered
        bets = {
            "NYG": (None, None), "WSH": (None, None), "DAL": (None, None), "PHI": (None, None),
            "BUF": (None, None), "MIA": (None, None), "NYJ": (None, None), "NE": (None, None),
            "GB": (None, None), "MIN": (None, None), "DET": (None, None), "CHI": (None, None),
            "CIN": (None, None), "CLE": (None, None), "BAL": (None, None), "PIT": (None, None),
            "SF": (None, None), "LAR": (None, None), "SEA": (None, None), "ARI": (None, None),
            "LV": (None, None), "DEN": (None, None), "KC": (None, None), "LAC": (None, None),
            "CAR": (None, None), "ATL": (None, None), "NO": (None, None), "TB": (None, None),
            "IND": (None, None), "TEN": (None, None), "HOU": (None, None), "JAX": (None, None),
        }
        with open(bet_file, 'w') as f:
            json.dump(bets, f, indent=4)
    else:
        with open(bet_file, 'r') as f:
            bets = json.load(f)

    return bets


if __name__ == "__main__":
    main()