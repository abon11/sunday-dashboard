import streamlit as st
import requests
from sleeper_pull import pull_lineup, pull_league_lineups, current_nfl_week, current_nfl_season, league_season
import espn_fantasy_pull
from espn_pull import pull_games, pull_live_spreads, EASTERN
from bet_storage import load_bets, save_bets, using_sheet
import html
import math
import statistics
import os
import re
import json
from datetime import datetime
from itertools import zip_longest
from urllib.parse import urlparse

SAVE_STATE_FILENAME = 'save_state.json'
# league_id = "1313968791364849664"  # FFF league
DEFAULT_USERNAME = "TitsBon"  # only used for a save_state.json from before the username was saved in it
SITES = {"sleeper": "Sleeper", "espn": "ESPN"}  # the fantasy sites a league can be on
REFRESH_SECONDS = 10  # how often the live area re-pulls scores

PLAYER_DIFF_SCALE = 10  # fantasy points ahead/behind where a player box is fully green/red
BET_DIFF_SCALE = 14     # points ahead of/behind the live line where a game row is fully green/red
RED, GREY, GREEN = (240, 106, 106), (226, 226, 226), (95, 220, 125)
BET_WON, BET_LOST = "#17e852", "#ff3b31"  # stronger colors for bets that are final
LIVE_SPREAD_SECONDS = 30  # how often the in-game betting lines are re-pulled

# names for sleeper's stat keys in the scoring breakdown (anything missing is shown as the cleaned up key)
STAT_LABELS = {
    "pass_yd": "Passing Yards", "pass_td": "Passing TD", "pass_int": "Interceptions Thrown", "pass_2pt": "2-Pt Pass",
    "rush_yd": "Rushing Yards", "rush_td": "Rushing TD", "rush_2pt": "2-Pt Rush",
    "rec": "Receptions", "rec_yd": "Receiving Yards", "rec_td": "Receiving TD", "rec_2pt": "2-Pt Reception",
    "fum": "Fumbles", "fum_lost": "Fumbles Lost", "fum_rec_td": "Fumble Recovery TD",
    "bonus_pass_yd_400": "400+ Passing Yards", "bonus_rush_yd_200": "200+ Rushing Yards",
    "bonus_rec_yd_200": "200+ Receiving Yards",
    "xpm": "PAT Made", "xpmiss": "PAT Missed", "fgmiss": "FG Missed", "fgm_0_19": "FG 0-19", "fgm_20_29": "FG 20-29",
    "fgm_30_39": "FG 30-39", "fgm_40_49": "FG 40-49", "fgm_50p": "FG 50+",
    "sack": "Sacks", "int": "Interceptions", "fum_rec": "Fumble Recoveries", "ff": "Forced Fumbles",
    "safe": "Safeties", "blk_kick": "Blocked Kicks", "def_td": "Defensive TD", "st_td": "Special Teams TD",
    "def_st_td": "Def/ST TD", "st_fum_rec": "ST Fumble Recoveries", "def_st_fum_rec": "Def/ST Fumble Recoveries",
    "st_ff": "ST Forced Fumbles", "def_st_ff": "Def/ST Forced Fumbles",
    "pts_allow_0": "0 Points Allowed", "pts_allow_1_6": "1-6 Points Allowed", "pts_allow_7_13": "7-13 Points Allowed",
    "pts_allow_14_20": "14-20 Points Allowed", "pts_allow_21_27": "21-27 Points Allowed",
    "pts_allow_28_34": "28-34 Points Allowed", "pts_allow_35p": "35+ Points Allowed",
}

TEAM_COLORS = {
    "NYG": "#003C7E", "WSH": "#773141", "DAL": "#041E42", "PHI": "#004C54",
    "BUF": "#00338D", "MIA": "#008E97", "NYJ": "#125740", "NE": "#002244",
    "GB": "#203731", "MIN": "#4F2683", "DET": "#0076B6", "CHI": "#0B162A",
    "CIN": "#FB4F14", "CLE": "#311D00", "BAL": "#241773", "PIT": "#FFB612",
    "SF": "#AA0000", "LAR": "#003594", "SEA": "#002244", "ARI": "#97233F",
    "LV": "#000000", "DEN": "#FB4F14", "KC": "#E31837", "LAC": "#0080C6",
    "CAR": "#0085CA", "ATL": "#A71930", "NO": "#D3BC8D", "TB": "#D50A0A",
    "IND": "#002C5F", "TEN": "#4B92DB", "HOU": "#03202F", "JAX": "#006778",
}

# Every box is laid out with flex/grid and sized by its column, so nothing has a fixed pixel width.
# Names that don't fit are cut off with "..." instead of wrapping.
CSS = """
<style>
    .block-container {padding-top: 2.5rem; padding-bottom: 1rem;}
    h1 {padding: 0; font-size: 1.9rem;}

    .sd-clip {white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
    .sd-num {font-variant-numeric: tabular-nums;}
    .sd-tm {flex: none; width: 3.2em; padding: 2px 0; border-radius: 5px; text-align: center;
            font-size: 0.8em; font-weight: 700;}

    /* state of the game a box belongs to */
    /* dark text goes on the contents rather than the box, so the live outline keeps the theme's text
       color and shows up in both light and dark mode */
    .sd-done > *, .sd-live > * {color: #111;}
    .sd-done {opacity: 0.7;}
    .sd-live {border-color: currentColor !important; font-weight: 700;}
    .sd-idle, .sd-nobet {background: rgba(128, 128, 128, 0.16); opacity: 1;}
    .sd-idle > *, .sd-nobet > * {color: inherit;}

    /* --- fantasy matchup --- */
    .sd-match {display: grid; grid-template-columns: minmax(0, 1fr) 3.4em minmax(0, 1fr);
               gap: 4px 6px; align-items: center; margin-bottom: 8px;}
    .sd-pc {display: flex; align-items: center; gap: 8px; min-width: 0; padding: 3px 10px;
            border: 2px solid transparent; border-radius: 8px; line-height: 1.25;}
    .sd-pc.sd-right {flex-direction: row-reverse; text-align: right;}
    .sd-pc.sd-idle, .sd-pc.sd-done {margin: 0 12px;}
    .sd-pc.sd-live {padding: 7px 10px;}
    .sd-who {flex: 1; min-width: 0;}
    .sd-sub {font-size: 0.72em; font-weight: 400; opacity: 0.75;}
    .sd-pts {flex: none; font-weight: 700;}
    .sd-diff {text-align: center; font-size: 0.85em; font-weight: 600;}
    .sd-up {color: #1c9a45;}
    .sd-down {color: #d64545;}
    .sd-head {margin-bottom: 4px; font-size: 1.15em; font-weight: 700;}
    .sd-head .sd-pts {font-size: 1.5em;}
    .sd-head .sd-pts .sd-sub {font-size: 0.45em;}
    .sd-win {font-size: 0.95em; white-space: nowrap;}
    /* scoring breakdown that pops up under a player's points while the mouse is on them */
    .sd-pc {position: relative;}
    .sd-pts {cursor: help;}
    .sd-head .sd-pts {cursor: auto;}
    .sd-pc > .sd-tip {display: none; position: absolute; top: calc(100% - 2px); right: 0; z-index: 1000;
                      padding: 8px 12px; border-radius: 8px; background: #1d2230; color: #fff;
                      box-shadow: 0 4px 14px rgba(0, 0, 0, 0.35); font-size: 0.82em; font-weight: 400;
                      text-align: left; white-space: nowrap; pointer-events: none;}
    .sd-pc.sd-right > .sd-tip {right: auto; left: 0;}
    .sd-pts:hover + .sd-tip {display: block;}
    .sd-pc.sd-done:has(.sd-pts:hover) {opacity: 1;}  /* a faded box would fade its popup too */
    .sd-tip-grid {display: grid; grid-template-columns: auto auto auto auto; gap: 3px 14px;}
    .sd-tip-grid > :not(:nth-child(4n + 1)) {text-align: right;}
    .sd-tip-head {font-size: 0.85em; opacity: 0.6;}
    .sd-tip-total {margin-top: 3px; padding-top: 4px; border-top: 1px solid rgba(255, 255, 255, 0.3); font-weight: 700;}
    /* skinny win probability bar: fills from my side, with a tick at 50% */
    .sd-median {grid-column: 1 / -1; margin: -4px 0 4px; text-align: center; font-size: 0.78em; opacity: 0.75;}
    .sd-winbar {grid-column: 1 / -1; position: relative; height: 5px; margin: 0 2px 6px; border-radius: 3px;
                background: rgba(128, 128, 128, 0.25);}
    .sd-winbar > div {height: 100%; border-radius: 3px;}
    .sd-winbar::after {content: ""; position: absolute; left: 50%; top: -3px; bottom: -3px; width: 2px;
                       margin-left: -1px; background: currentColor; opacity: 0.6;}

    /* --- game slate --- */
    .sd-game {display: grid; grid-template-columns: 1.2em 3.2em 4.4em 3.2em 1.2em minmax(0, 1fr) auto;
              gap: 4px; align-items: center; margin-bottom: 4px; padding: 2px 8px;
              border: 2px solid transparent; border-radius: 8px;}
    .sd-game.sd-live {padding: 5px 8px;}
    .sd-game.sd-settled {opacity: 1; font-weight: 600;}
    .sd-game .sd-tm {width: auto; font-size: 0.85em;}
    /* the team you bet on: double ring (light then dark) so it stands out on any row color */
    .sd-tm.sd-pick {box-shadow: 0 0 0 1.5px #fff, 0 0 0 3.5px #111;}
    .sd-score {text-align: center; font-weight: 700;}
    .sd-when {margin-left: 6px; font-size: 0.85em; font-weight: 400;}
    .sd-bet {font-size: 0.85em; text-align: right; white-space: nowrap;}
    /* tighten the rows when the slate column gets narrow (small window) */
    .sd-slate {container-type: inline-size;}
    @container (max-width: 400px) {
        .sd-game {grid-template-columns: 1.1em 2.9em 3.4em 2.9em 1.1em minmax(0, 1fr) auto;
                  gap: 2px; padding-left: 4px; padding-right: 4px; font-size: 0.82em;}
        .sd-when {margin-left: 2px;}
    }

    div[data-testid="stForm"] button p {white-space: nowrap;}
    /* streamlit's "Press Enter to submit form" hint is drawn inside the text box, on top of a long league id */
    div[data-testid="InputInstructions"] {display: none;}
    div[data-testid="stPopoverBody"] {min-width: 300px;}

    /* --- keys --- */
    .sd-legend {margin-top: 10px; padding: 8px 12px 10px; border: 1px solid rgba(128, 128, 128, 0.3);
                border-radius: 8px; font-size: 0.78em;}
    .sd-legend-title {margin-bottom: 6px; font-size: 0.9em; font-weight: 700; letter-spacing: 0.08em;
                      text-transform: uppercase; opacity: 0.6;}
    .sd-legend-grid {display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 6px 20px;}
    .sd-legend-item {display: flex; align-items: center; gap: 10px; line-height: 1.25;}
    .sd-legend-key {flex: none; width: 6.2em; text-align: center; font-weight: 600; white-space: nowrap;}
    .sd-legend-text {opacity: 0.8;}
    .sd-swatch {display: inline-block; width: 100%; height: 0.9em; border-radius: 3px; vertical-align: middle;
                background: linear-gradient(90deg, #f06a6a, #e2e2e2, #5fdc7d);}
    .sd-key {display: inline-block; padding: 0 7px; border: 2px solid transparent; border-radius: 5px;}
</style>
"""


def main():
    st.set_page_config(page_title="Football Sunday Dashboard", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)

    # --- Who is looking ---
    # The fantasy site, league and who you are in it live in the page's url, so everybody has their own link to
    # bookmark and nobody shares settings:  ?site=sleeper&league=...&user=<sleeper username>
    #                                       ?site=espn&league=...&team=<espn team id>
    # When you run it on your own computer, a link without them falls back to what was last saved on it.
    # A hosted copy never remembers anyone: a bare link there always shows the welcome screen.
    save_state = load_save_state()
    if "selected_week" not in st.session_state:
        # the week last picked on this machine, or the current NFL week for a first visit
        st.session_state["selected_week"] = save_state.get("current_week") or current_nfl_week()

    params = st.query_params
    if params.get("league"):
        site = params.get("site", "sleeper")  # links from before espn was added don't say which site
        league_id = params.get("league")
        who = params.get("team" if site == "espn" else "user", "")
    else:
        site = save_state.get("site", "sleeper")
        league_id = save_state.get("league_id", "")
        if site == "espn":
            who = save_state.get("team", "")
        else:
            who = save_state.get("username") or (DEFAULT_USERNAME if league_id else "")

    if not valid_settings(site, league_id, who):
        st.markdown("### Welcome to the Football Sunday Dashboard")
        st.info("Pick the site your fantasy league is on and enter your league to load your matchup. "
                "After that, bookmark the page: the link remembers it.")
        settings_panel("welcome", site if site in SITES else "sleeper", "", "")
        st.stop()
    link = {"site": site, "league": league_id, "team" if site == "espn" else "user": who}
    if params.to_dict() != link:
        params.from_dict(link)

    # --- Title and Menu ---
    title_col, week_col, settings_col = st.columns([6, 1.3, 1.2], vertical_alignment="bottom")
    with week_col:
        st.selectbox(
            "Select Week",
            options=range(1, 19),
            format_func=lambda week: f"Week {week}",
            label_visibility="collapsed",
            key="selected_week",
            on_change=lambda: update_save_state(current_week=st.session_state["selected_week"]),
        )
    with settings_col:
        with st.popover("League", width="stretch"):
            settings_panel("settings", site, league_id, who)
    title_col.title(f"Football Sunday Dashboard - Week {st.session_state['selected_week']}")

    live_view(site, league_id, who, st.session_state["selected_week"])


def running_locally():
    """True when the page is being viewed on the computer running it, rather than a hosted copy."""
    try:
        return urlparse(st.context.url).hostname in ("localhost", "127.0.0.1")
    except Exception:
        return False

def load_save_state():
    if not running_locally() or not os.path.exists(SAVE_STATE_FILENAME):
        return {}
    with open(SAVE_STATE_FILENAME, 'r') as f:
        return json.load(f)

def update_save_state(**changes):
    if not running_locally():
        return
    save_state = load_save_state()
    save_state.update(changes)
    with open(SAVE_STATE_FILENAME, 'w') as f:
        json.dump(save_state, f, indent=4)

def valid_settings(site, league_id, who):
    """
    Whether the site, league and person from the link look right. They end up in the addresses we request and
    in the bets sheet, so anything that isn't a plain id or username is turned away.
    """
    if site not in SITES or not str(league_id).isdigit() or len(str(league_id)) > 25:
        return False
    if site == "espn":
        return str(who).isdigit() and len(str(who)) <= 4
    return re.fullmatch(r"[A-Za-z0-9_.\-]{1,50}", str(who)) is not None

def apply_settings(site, league_id, who):
    """Puts a new league in the url (and remembers it on your own computer), then reloads with it."""
    if not valid_settings(site, league_id, who):
        st.error("That doesn't look right. The league ID is a number, and a Sleeper username has no spaces.")
        return
    who_key = "team" if site == "espn" else "user"
    st.query_params.from_dict({"site": site, "league": league_id, who_key: who})
    update_save_state(site=site, league_id=league_id, **{"team" if site == "espn" else "username": who})
    st.rerun()

def settings_panel(key, site, league_id, who):
    """Where the fantasy site, league and who you are get entered (the welcome screen) or changed (the League button)."""
    choice = st.radio("Fantasy site", list(SITES), index=list(SITES).index(site), format_func=SITES.get,
                      horizontal=True, key=f"{key}_site")

    if choice == "sleeper":
        with st.form(f"{key}_sleeper", border=False):
            new_username = st.text_input("Sleeper Username", value=who if site == "sleeper" else "",
                                         placeholder="Your Sleeper username")
            new_league = st.text_input(
                "Sleeper League ID",
                value=league_id if site == "sleeper" else "",
                placeholder="The long number in your league's url",
                help="Open your league on sleeper.com: it is the number at the end of the address.",
            )
            if st.form_submit_button("Set", type="primary") and new_username.strip() and new_league.strip():
                apply_settings("sleeper", new_league.strip(), new_username.strip())
        return

    # ESPN has no public username to find your team by, so it is two steps: the league, then pick your team from it
    new_league = st.text_input(
        "ESPN League ID",
        value=league_id if site == "espn" else "",
        placeholder="Type the number, then press Enter",
        help="Open your league on espn.com: it is the number after leagueId= in the address. "
             "The league has to be viewable to the public (League Manager Tools, Basic Settings).",
        key=f"{key}_espn_league",
    ).strip()
    if not new_league:
        return
    if not new_league.isdigit():
        st.error("The ESPN League ID is a number.")
        return
    try:
        teams = fetch_espn_teams(new_league)
    except (requests.RequestException, ValueError) as e:
        st.error(str(e) if isinstance(e, ValueError) else "Couldn't reach ESPN, try again in a moment.")
        return
    labels = {str(team_id): f"{name} ({owner})" if owner else name for team_id, name, owner in teams}
    team_ids = list(labels)
    new_team = st.selectbox("Your team", team_ids, format_func=labels.get, key=f"{key}_espn_team",
                            index=team_ids.index(who) if site == "espn" and who in team_ids else 0)
    if st.button("Set", type="primary", key=f"{key}_espn_set"):
        apply_settings("espn", new_league, new_team)


# The ttl sits just under the refresh interval: each auto refresh pulls fresh data, but reruns caused
# by clicking something (saving a bet etc.) reuse what was just pulled instead of hitting the apis again.
@st.cache_data(ttl=REFRESH_SECONDS - 1, show_spinner=False)
def fetch_games(week):
    return pull_games(week)

@st.cache_data(ttl=REFRESH_SECONDS - 1, show_spinner=False, max_entries=200)
def fetch_lineups(site, league_id, who, week):
    if site == "espn":
        return espn_fantasy_pull.pull_lineup(league_id, who, week)
    return pull_lineup(league_id, who, week)

# every team's lineup, for the league median. It reuses the pulls fetch_lineups just made, so no extra requests
@st.cache_data(ttl=REFRESH_SECONDS - 1, show_spinner=False, max_entries=200)
def fetch_league_lineups(site, league_id, week):
    if site == "espn":
        return espn_fantasy_pull.pull_league_lineups(league_id, week)
    return pull_league_lineups(league_id, week)

@st.cache_data(ttl=3600, show_spinner=False, max_entries=200)
def fetch_espn_teams(league_id):
    return espn_fantasy_pull.league_teams(league_id)

# The in-game lines take one request per live game, and move slower than the score, so they refresh less often.
@st.cache_data(ttl=LIVE_SPREAD_SECONDS, show_spinner=False)
def fetch_live_spreads(week):
    return pull_live_spreads(fetch_games(week))


@st.fragment(run_every=REFRESH_SECONDS)
def live_view(site, league_id, who, week):
    """
    Everything that updates live. Being a fragment, only this part reruns (every REFRESH_SECONDS, or when
    a bet is saved) - the browser never reloads the page.
    """
    try:
        games = fetch_games(week)
        my_lineup, opp_lineup = fetch_lineups(site, league_id, who, week)
        live_spreads = fetch_live_spreads(week)
        st.session_state["last_pull"] = (site, league_id, who, week, games, my_lineup, opp_lineup, live_spreads, datetime.now(EASTERN))
    except (requests.RequestException, ValueError) as e:
        st.warning(f"Couldn't refresh the data, will keep trying: {e}")
        last_pull = st.session_state.get("last_pull")
        if last_pull is None or last_pull[:4] != (site, league_id, who, week):
            return
    _, _, _, _, games, my_lineup, opp_lineup, live_spreads, pulled_at = st.session_state["last_pull"]

    for lineup in (my_lineup, opp_lineup):
        lineup.assign_game_status(games)
        lineup.order_list()

    # the league median is only a comparison line, so if it can't be worked out the page just goes without it
    try:
        league_lineups = fetch_league_lineups(site, league_id, week)
        for lineup in league_lineups:
            lineup.assign_game_status(games)
    except (requests.RequestException, ValueError):
        league_lineups = []

    # Whose bets these are. Sleeper has usernames, so bets follow the person across their leagues. ESPN doesn't
    # give us one, so there they belong to the team.
    bet_user = who if site == "sleeper" else f"espn-{league_id}-{who}"
    # The local bet files are one set of bets shared by everybody looking at the page. That is fine on your own
    # computer, but a hosted copy must never fall back to them or everyone sees (and edits) the same bets.
    shared_files = running_locally()
    try:
        if not shared_files and not using_sheet():
            st.warning("Bets are not being saved on this copy of the dashboard: its Google Sheet is not connected "
                       "(the app's Secrets need `bets_sheet_id` and `[gcp_service_account]`). "
                       "Bets you enter will only last until you close this tab.")
        bets = load_bets(bet_user, bet_season(site, league_id), week, shared_files)
    except Exception as e:  # the google sheet can fail in a lot of ways, none of them should take the page down
        print(f"Could not load bets for {bet_user}: {e}")  # details go to the log, not onto everybody's screen
        st.warning("Couldn't load your bets, will keep trying.")
        bets = {}
    if st.session_state.pop("bet_error", False):
        st.warning("That bet change was not saved, try again in a moment.")

    left, right = st.columns([5, 3], gap="medium")
    with left:
        st.markdown(matchup_html(my_lineup, opp_lineup, league_lineups), unsafe_allow_html=True)
        show_bet_form(games, bet_user, site, league_id, week, shared_files)
        st.markdown(matchup_legend(site), unsafe_allow_html=True)
    with right:
        st.markdown(slate_html(games, bets, live_spreads), unsafe_allow_html=True)
    st.caption(f"Updates every {REFRESH_SECONDS}s. Last updated {pulled_at.strftime('%-I:%M:%S %p')} ET")


######################
# Fantasy matchup
######################

def matchup_html(my_lineup, opp_lineup, league_lineups=()):
    """Builds both lineups as one mirrored grid: my player | point difference | their player."""
    lead = my_lineup.total_points - opp_lineup.total_points
    win_prob = win_probability(my_lineup, opp_lineup)
    rows = [
        team_header(my_lineup, "left"),
        f'<div class="sd-diff sd-num {diff_class(lead)}" title="Your lead, and your estimated chance to win">{lead:+.2f}'
        f'<div class="sd-win {diff_class(win_prob - 0.5)}">win {win_prob:.0%}</div></div>',
        team_header(opp_lineup, "right"),
        f'<div class="sd-winbar" title="Estimated chance to win: {win_prob:.0%}">'
        f'<div style="width:{win_prob:.1%}; background:{WIN_BAR_COLORS[diff_class(win_prob - 0.5)]};"></div></div>',
    ]
    if len(league_lineups) > 1:
        # the middle score of every team in the league this week, and the middle of their projected finals
        median = statistics.median(lineup.total_points for lineup in league_lineups)
        projected_median = statistics.median(lineup.projected_points for lineup in league_lineups)
        rows.append(
            f'<div class="sd-median sd-num" title="The median score of all {len(league_lineups)} teams in the league this week, and the median of their projected finals">'
            f'League median <b>{median:.2f}</b> · projected <b>{projected_median:.1f}</b></div>'
        )
    for p, op in zip_longest(my_lineup.player_list, opp_lineup.player_list):
        p_points = p.player_points if p else 0
        op_points = op.player_points if op else 0
        diff = p_points - op_points
        rows.append(player_box(p, diff, "left"))
        rows.append(f'<div class="sd-diff sd-num {diff_class(diff)}">{f"{diff:+.1f}" if abs(diff) >= 0.05 else "-"}</div>')
        rows.append(player_box(op, -diff, "right"))

    return f'<div class="sd-match">{"".join(rows)}</div>'

def team_header(lineup, side):
    return (
        f'<div class="sd-pc sd-head sd-{side}">'
        f'<div class="sd-who"><div class="sd-clip">{html.escape(lineup.team_name)}</div>'
        f'<div class="sd-sub sd-clip">{html.escape(lineup.username)}</div></div>'
        f'<div class="sd-pts sd-num">{lineup.total_points:.2f}'
        f'<div class="sd-sub">proj {lineup.projected_points:.1f}</div></div>'
        '</div>'
    )

def win_probability(my_lineup, opp_lineup):
    """
    Estimated chance my_lineup wins: the gap between the two projected finals, measured against how much
    the points still to come typically swing (normal approximation). Sleeper doesn't publish theirs.
    """
    diff = my_lineup.projected_points - opp_lineup.projected_points
    variance = sum(p.projection_std ** 2 for p in my_lineup.player_list + opp_lineup.player_list)
    if variance == 0:
        return 1.0 if diff > 0 else 0.0 if diff < 0 else 0.5
    return 0.5 * (1 + math.erf(diff / math.sqrt(2 * variance)))

def player_box(p, diff, side):
    if p is None:
        return '<div></div>'
    state = state_class(p.game_state)
    # only color by the matchup once the player's game has started
    background = "" if state == "sd-idle" else f' style="background:{diff_color(diff, PLAYER_DIFF_SCALE)};"'
    ball = " 🏈" if p.possession else ""
    name = html.escape(f"{p.first_name} {p.last_name}")
    # once a game is final the projection is just the score, so only show it while there is something left
    projection = f'<div class="sd-sub">proj {p.live_projection:.1f}</div>' if p.game_state in ("pre", "in") else ""
    return (
        f'<div class="sd-pc sd-{side} {state}"{background}>'
        f'{team_badge(p.team)}'
        f'<div class="sd-who"><div class="sd-clip" title="{name}">{name}</div>'
        f'<div class="sd-sub sd-clip">{html.escape(p.position)} · {html.escape(p.game_detail or "")}{ball}</div></div>'
        f'<div class="sd-pts sd-num">{p.player_points:.1f}{projection}</div>'
        f'{breakdown_popup(p)}'
        '</div>'
    )

def breakdown_popup(p):
    """The little table shown when hovering a player's points: each stat, points per, points, and the total."""
    if p.position == "None":
        return ""
    if not p.breakdown:
        return '<div class="sd-tip">No stats yet</div>'
    cells = ['<span class="sd-tip-head">Stat</span><span class="sd-tip-head"></span>'
             '<span class="sd-tip-head">Pts per</span><span class="sd-tip-head">Points</span>']
    # biggest contributions first
    for stat, amount, per, points in sorted(p.breakdown, key=lambda row: -abs(row[3])):
        # sleeper gives stat keys like rush_yd, espn_fantasy_pull already gives readable names
        label = STAT_LABELS.get(stat) or (stat.replace("_", " ").title() if stat.islower() else stat)
        cells.append(f'<span>{html.escape(label)}</span><span>{amount:g}</span><span>{per:g}</span><span>{points:.2f}</span>')
    cells.append(f'<span class="sd-tip-total">Total</span><span class="sd-tip-total"></span>'
                 f'<span class="sd-tip-total"></span><span class="sd-tip-total">{p.player_points:.2f}</span>')
    return f'<div class="sd-tip"><div class="sd-tip-grid sd-num">{"".join(cells)}</div></div>'


######################
# Game slate and bets
######################

def slate_html(games, bets, live_spreads):
    rows = []
    summary = {"won": 0, "lost": 0, "push": 0, "ahead": 0, "behind": 0, "even": 0, "upcoming": 0}
    for game in sort_games(games, bets, live_spreads):
        state = state_class(game["state"])
        bet_team, spread = active_bet(game, bets)
        margin = bet_margin(game, bets, live_spreads)

        background = ""
        bet_string = ""
        if bet_team is not None:
            bet_string = f"{html.escape(bet_team)} ML" if spread == 0 else f"{html.escape(bet_team)} {spread:+.1f}"
            if game["state"] == "pre":
                summary["upcoming"] += 1
            elif game["state"] == "post":
                result = "won" if margin > 0 else "lost" if margin < 0 else "push"
                summary[result] += 1
                bet_string = f'{ {"won": "✓", "lost": "✗", "push": "="}[result] } {bet_string}'
                # set in stone: full strength color and no fade
                background = {"won": BET_WON, "lost": BET_LOST, "push": diff_color(0, 1)}[result]
                state += " sd-settled"
            else:
                summary["ahead" if margin > 0 else "behind" if margin < 0 else "even"] += 1
                if bet_team in live_spreads:
                    live = live_spreads[bet_team]
                    bet_string = f'{bet_string} · now {"PK" if live == 0 else f"{live:+g}"}'
                else:
                    bet_string = f"{bet_string} ({margin:+g})"
                background = diff_color(margin, BET_DIFF_SCALE)
        # no bet (or not started): neutral row, but it keeps the bold outline if it is live
        style = f' style="background:{background};"' if background else ""
        if not background:
            state += " sd-nobet"

        away_team = game["away_team"]; home_team = game["home_team"]
        rows.append(
            f'<div class="sd-game {state}"{style}>'
            f'<span>{"🏈" if game["possession"] == away_team else ""}</span>'
            f'{team_badge(away_team, picked=bet_team == away_team)}'
            f'<span class="sd-score sd-num">{game["away_score"]} - {game["home_score"]}</span>'
            f'{team_badge(home_team, picked=bet_team == home_team)}'
            f'<span>{"🏈" if game["possession"] == home_team else ""}</span>'
            f'<span class="sd-when sd-clip">{html.escape(game["detail"])}</span>'
            f'<span class="sd-bet sd-num">{bet_string}</span>'
            '</div>'
        )

    if sum(summary.values()) == 0:
        summary_string = "No bets yet, add one under the lineups."
    else:
        parts = []
        if summary["won"] or summary["lost"] or summary["push"]:
            record = f'{summary["won"]}-{summary["lost"]}' + (f'-{summary["push"]}' if summary["push"] else "")
            parts.append(f"<b>{record}</b> final")
        for key in ("ahead", "behind", "even", "upcoming"):
            if summary[key]:
                parts.append(f"<b>{summary[key]}</b> {key}")
        summary_string = "Bets: " + " · ".join(parts)

    return (
        '<div class="sd-pc sd-head"><div class="sd-who">Full Slate'
        f'<div class="sd-sub sd-clip">{summary_string}</div></div></div>'
        f'<div class="sd-slate">{"".join(rows)}</div>{SLATE_LEGEND}'
    )

def bet_season(site, league_id):
    return league_season(league_id) if site == "sleeper" else current_nfl_season()

def show_bet_form(games, bet_user, site, league_id, week, shared_files):
    teams = [team for game in games for team in (game["away_team"], game["home_team"])]
    opponent = {}
    for game in games:
        opponent[game["away_team"]] = f'at {game["home_team"]}'
        opponent[game["home_team"]] = f'vs {game["away_team"]}'

    # The buttons save through callbacks, which run before the live area redraws, so the slate above
    # shows the change straight away without rerunning anything extra.
    with st.form("bet_form"):
        team_col, spread_col, save_col, remove_col, clear_col = st.columns([2.2, 1.3, 1, 1.1, 1], vertical_alignment="bottom")
        team_col.selectbox("Bet on", options=teams, format_func=lambda t: f"{t} ({opponent[t]})", key="bet_team")
        spread_col.number_input("Spread", value=0.0, step=0.5, format="%.1f", key="bet_spread",
                                help="The spread you got, like -2.5 or 3.5. Leave at 0 for a moneyline bet.")
        save_col.form_submit_button("Save", type="primary", width="stretch",
                                    on_click=change_bets, args=("save", bet_user, site, league_id, week, shared_files))
        remove_col.form_submit_button("Remove", width="stretch", help="Remove the bet on the selected team",
                                      on_click=change_bets, args=("remove", bet_user, site, league_id, week, shared_files))
        clear_col.form_submit_button("Clear", width="stretch", help="Remove every bet this week",
                                     on_click=change_bets, args=("clear", bet_user, site, league_id, week, shared_files))

def change_bets(action, bet_user, site, league_id, week, shared_files):
    try:
        # if the bets can't be read we stop here, rather than saving over them with an incomplete set
        season = bet_season(site, league_id)
        bets = load_bets(bet_user, season, week, shared_files)
        team = st.session_state.get("bet_team")
        if action == "clear":
            bets = {}
        elif team is None:
            return
        elif action == "remove":
            bets.pop(team, None)
        else:
            spread = round(st.session_state["bet_spread"] * 2) / 2.0  # nearest 0.5
            print(f"Saved bet: {team} {spread:+.1f}")   # <-- prints to console
            bets[team] = (spread, datetime.now().timestamp())
        save_bets(bet_user, league_id, season, week, bets, shared_files)
    except Exception as e:
        print(f"Could not save bets for {bet_user}: {e}")
        st.session_state["bet_error"] = True

def active_bet(game, bets):
    """
    Returns (team, spread) for the bet on this game, or (None, None) if there isn't one. If both teams
    have a bet we take the more recently placed one (we could clear the other bet but unnecessary).
    """
    placed = [(bets[team][1], team) for team in (game["away_team"], game["home_team"]) if team in bets]
    if not placed:
        return None, None
    team = max(placed)[1]
    return team, float(bets[team][0])

def bet_margin(game, bets, live_spreads):
    """
    How far ahead the bet on this game is (negative = behind). 0 if no bet.
    While the game is live this is measured against the live spread: holding +7.5 when the line is now +5.5
    is 2 ahead, so a bet starts out neutral at kickoff and only moves as the game does. The live line closes
    in on the real score as time runs out, so it lands on the same number as the final result, which is what
    we use once the game is over (or if there is no live line posted).
    """
    team, spread = active_bet(game, bets)
    if team is None:
        return 0
    if game["state"] == "in" and team in live_spreads:
        return spread - live_spreads[team]
    if team == game["away_team"]:
        return game["away_score"] - game["home_score"] + spread
    return game["home_score"] - game["away_score"] + spread

def sort_games(games, bets, live_spreads):
    def sort_key(game):
        # group order: in-progress → final → TBD
        group = {"in": 0, "post": 1}.get(game["state"], 2)
        # negative margin → descending within group
        return (group, -bet_margin(game, bets, live_spreads))

    return sorted(games, key=sort_key)


######################
# Shared pieces
######################

def state_class(game_state):
    return {"in": "sd-live", "post": "sd-done"}.get(game_state, "sd-idle")

def diff_class(diff):
    return "sd-up" if diff > 0 else "sd-down" if diff < 0 else ""

def diff_color(diff, scale):
    """
    Returns a hex color smoothly transitioning from red (down by scale)
    to grey (even) to green (up by scale).
    """
    normalized = max(-1.0, min(1.0, diff / scale))
    target = GREEN if normalized >= 0 else RED
    weight = abs(normalized)
    return "#%02x%02x%02x" % tuple(round(g + (t - g) * weight) for g, t in zip(GREY, target))

def team_badge(team, picked=False):
    color = TEAM_COLORS.get(team, "#888888")
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    # dark text on the few light team colors (PIT, NO) so the abbreviation stays readable
    text = "#111" if (0.299 * r + 0.587 * g + 0.114 * b) > 160 else "white"
    pick = " sd-pick" if picked else ""
    return f'<span class="sd-tm{pick}" style="background:{color}; color:{text};">{html.escape(team)}</span>'

def legend_html(title, items):
    """Builds a key box from (symbol html, description) pairs, laid out in aligned columns."""
    cells = "".join(
        f'<div class="sd-legend-item"><span class="sd-legend-key">{key}</span>'
        f'<span class="sd-legend-text">{text}</span></div>'
        for key, text in items
    )
    return (f'<div class="sd-legend"><div class="sd-legend-title">{title}</div>'
            f'<div class="sd-legend-grid">{cells}</div></div>')

WIN_BAR_COLORS = {"sd-up": "#1c9a45", "sd-down": "#d64545", "": "#9a9a9a"}

def matchup_legend(site):
    return legend_html("Lineup key", [
        ('<span class="sd-swatch"></span>', f"Performance relative to the player across from them"),
        ('<span class="sd-key sd-live" style="background:#e2e2e2;"><span>Bold</span></span>', "Playing right now"),
        ('<span class="sd-key sd-done" style="background:#e2e2e2;"><span>Faded</span></span>', "Game is final"),
        ('<span class="sd-key sd-idle">Grey</span>', "Not started, or on bye"),
        ("🏈", "Their team has the ball"),
        ("pts", "Hover a player's points for their scoring breakdown"),
        ("proj", f"Projected final: from {SITES[site]}'s projections"),
        ("win %", f"Estimated from the projections (not {SITES[site]}'s calculation)"),
    ])

SLATE_LEGEND = legend_html("Slate key", [
    ('<span class="sd-swatch"></span>', f"Your bet is worse to better than the live spread (full color at {BET_DIFF_SCALE}+ pts)"),
    ('<span class="sd-tm sd-pick" style="display:inline-block; width:3.2em; background:#555; color:white;">TM</span>', "The team you bet on"),
    ("now -3.5", "The live spread for your team"),
    ("(+3)", "No live line posted: covering by 3 on the scoreboard"),
    (f'<span class="sd-key" style="background:{BET_WON}; color:#111;">✓</span> '
     f'<span class="sd-key" style="background:{BET_LOST}; color:#111;">✗</span>', "Final: bet won / lost"),
    ("🏈", "Has the ball"),
])


if __name__ == "__main__":
    main()
