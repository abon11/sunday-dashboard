import streamlit as st
import pandas as pd
from sleeper_pull import pull_lineup
from espn_pull import pull_games
import matplotlib.colors as mcolors

def main():
    league_id = '1180303931006689280'  # FFF league
    username = 'TitsBon'
    week = 6
    my_lineup, opp_lineup = pull_lineup(league_id, username, week)

    # --- UI ---
    st.set_page_config(page_title="Football Sunday Dashboard", layout="wide")
    st.markdown(
        """
        <style>
            /* Reduce top margin & tighten page spacing */
            .block-container {
                padding-top: 1rem;
                padding-bottom: 1rem;
            }
            /* Optional: slightly reduce space under headers */
            h1, h2, h3 {
                margin-top: 0rem;
                margin-bottom: 0.5rem;
            }
        </style>
        """,
        unsafe_allow_html=True
    )
    top_left, top_right = st.columns([3, 1])

    with top_left:
        st.title(f"Football Sunday Dashboard - Week {week}")

    with top_right:
        st.write("")  # spacer line
        st.write("")
        selection = st.selectbox(
            "Menu",
            ["Add Bet", "Other", "Pick'em", "Bets"],
            index=0,
            label_visibility="collapsed"  # hides the label so it looks clean
        )
    # st.title(f"Football Sunday Dashboard - Week {week}")

    col1, col2, col3 = st.columns(3)
    # Render each team
    with col1:
        show_lineup(my_lineup, opp_lineup)

    with col2:
        show_lineup(opp_lineup, my_lineup)

    with col3:
        show_games(week)

    # with col4:
    #     st.subheader("test col")

# helper to render a Lineup
def show_lineup(lineup, other_lineup):
    st.subheader(f"{lineup.team_name} ({lineup.username})")
    st.metric("Total Points", f"{lineup.total_points:.2f}")
    # st.write("---")

    lineup.order_list()
    other_lineup.order_list()

    for p, op in zip(lineup.player_list, other_lineup.player_list):
        color = diff_color(p.player_points, op.player_points)
        # st.markdown(
        #     f"<div style='border-left: 10px solid {color}; padding: 2px 10px; margin-bottom: 4px; border-radius: 6px;'>"
        #     f"<b>{p.first_name} {p.last_name}</b> ({p.team} {p.position}) - "
        #     f"{p.player_points:.1f} pts "
        #     # f"<span style='color: #888'>[{p.injury_status}]</span>"
        #     f"</div>",
        #     unsafe_allow_html=True
        # )
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

def show_games(week):
    # For this, the next thing i want to do is make each team clickable, then it brings up a menu basically so you can click on 
    # a team to bet on them, and the menu has an option to say you bet them ML or spread (and enter spread), then it shows up
    # at the top with your bet choice and the background of the whole game is green/red slider depending on what the live spread
    # is in relation to the current spread. It would also be displayed to the right of the game
    st.subheader(f"Full Slate")
    games = pull_games(week)
    for game in games:
        line = (
            f"{game['away_team']:<3} {int(game['away_score']):>2} - "
            f"{int(game['home_score']):>2} {game['home_team']:<3} | "
            f"{('Q'+str(game['quarter'])+' '+game['clock']) if game['status']=='STATUS_IN_PROGRESS' else game['status']}"
        )
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

        def team_span(team):
            bg = team_colors.get(team, "#CCCCCC")
            return (
                f"<span style='display:inline-block; width:4ch; text-align:center; "
                f"background-color:{bg}; color:white; border-radius:4px; "
                f"font-weight:bold; padding:0px 3px;'>{team}</span>"
            )
        line = (
            f"{team_span(game['away_team']):<3} {f"{int(game['away_score']):>2}"} - "
            f"{f"{int(game['home_score']):>2}"} {team_span(game['home_team']):<3} | {game["status"]}"
        )
        st.markdown(
            f"""
            <div style='
                font-family: monospace;
                white-space: pre;
                padding: 6px 10px;
                margin-bottom: 4px;
                border-radius: 6px;
                background-color: #f5f5f5;
                font-size: 15px;
            '>{line}</div>
            """,
            unsafe_allow_html=True
        )

if __name__ == "__main__":
    main()