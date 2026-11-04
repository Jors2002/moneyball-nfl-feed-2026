"""Read-only Sleeper league reconstruction. Outputs are private, never public feeds."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
import math
from pathlib import Path

STARTERS = ['QB', 'RB', 'RB', 'WR', 'WR', 'TE', 'WRRB_FLEX', 'K', 'DEF']
# nflverse's documented offensive fantasy_points_ppr formula.
NFLVERSE_SCORING = {
    'pass_yd': .04, 'pass_td': 4., 'pass_int': -2., 'rush_yd': .1,
    'rush_td': 6., 'rec_yd': .1, 'rec_td': 6., 'rec': 1.,
    'pass_2pt': 2., 'rush_2pt': 2., 'rec_2pt': 2., 'fum_lost': -2.,
}


def _int(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f'Invalid {name}')
    return value


def score_decimal(settings, integer_key, decimal_key):
    """Sleeper splits positive PF/PA into integer and hundredths components."""
    integer = _int(settings.get(integer_key, 0), integer_key)
    hundredths = _int(settings.get(decimal_key, 0), decimal_key)
    if hundredths > 99:
        raise ValueError(f'Invalid hundredths {decimal_key}')
    return float(Decimal(integer) + Decimal(hundredths) / 100)


def scoring_compatibility(scoring):
    if not isinstance(scoring, dict):
        raise ValueError('Scoring must be an object')
    changes = {}
    for key, default in NFLVERSE_SCORING.items():
        raw = scoring.get(key, 0.)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
            raise ValueError(f'Invalid scoring coefficient {key}')
        if raw != default:
            changes[key] = {'nflverse': default, 'league': raw, 'delta': raw-default}
    pass_only = set(changes) <= {'pass_int'}
    return {
        'base': 'nflverse fantasy_points_ppr',
        'status': 'EXACT_FOR_LISTED_OFFENSIVE_COMPONENTS' if not changes else
                  'ADJUST_PASS_INTERCEPTIONS' if pass_only else 'RECOMPUTE_OFFENSIVE_SCORING',
        'differences': changes,
        'pass_interception_adjustment': changes.get('pass_int', {}).get('delta', 0.),
        'formula': 'fantasy_points_ppr + delta_pass_int * passing_interceptions' if pass_only else None,
        'caveats': [
            'K and DEF require separate scoring models.',
            'Special-teams, fumble-recovery touchdowns and custom bonuses require component audit.',
            'This coefficient audit is not proof that all source components are complete.',
        ],
    }


def build(league, rosters, bracket, nfl):
    if not isinstance(league, dict) or not isinstance(nfl, dict):
        raise ValueError('Invalid league/state objects')
    settings = league.get('settings', {})
    if league.get('season') != nfl.get('season'):
        raise ValueError('League and NFL state seasons disagree')
    slots = league.get('roster_positions')
    if not isinstance(slots, list) or [s for s in slots if s != 'BN'] != STARTERS:
        raise ValueError('Expected nine legal starters with RB/WR-only FLEX')
    if settings.get('num_teams') != 10 or not isinstance(rosters, list) or len(rosters) != 10:
        raise ValueError('Expected ten teams')
    if settings.get('playoff_teams') != 6 or settings.get('playoff_week_start') != 15:
        raise ValueError('Expected six playoff teams starting week 15')
    if settings.get('reserve_slots') != 1 or slots.count('BN') != 5:
        raise ValueError('Expected five bench and one IR slots')
    ids = [r.get('roster_id') for r in rosters]
    if len(set(ids)) != 10 or any(not isinstance(x, int) or isinstance(x, bool) for x in ids):
        raise ValueError('Duplicate or invalid roster IDs')
    standings = []
    seen_player_ids = set()
    for roster in rosters:
        stats = roster.get('settings', {})
        players, reserve, starters = roster.get('players'), roster.get('reserve') or [], roster.get('starters')
        if not isinstance(players, list) or len(players) != len(set(players)):
            raise ValueError('Invalid roster players')
        if any(not isinstance(player, str) or not player for player in players):
            raise ValueError('Invalid player ID')
        if seen_player_ids.intersection(players):
            raise ValueError('Duplicate cross-team player ownership')
        seen_player_ids.update(players)
        if not isinstance(starters, list) or len(starters) != 9:
            raise ValueError('Expected nine starter entries')
        nonempty = [p for p in starters if p not in ('0', None)]
        if len(set(nonempty)) != len(nonempty) or not set(nonempty) <= set(players):
            raise ValueError('Invalid starter ownership/duplicates')
        if not set(reserve) <= set(players) or len(reserve) > 1:
            raise ValueError('Invalid IR roster membership')
        standings.append({'roster_id': roster['roster_id'],
                          'wins': _int(stats.get('wins'), 'wins'),
                          'losses': _int(stats.get('losses'), 'losses'),
                          'ties': _int(stats.get('ties', 0), 'ties'),
                          'pf': score_decimal(stats, 'fpts', 'fpts_decimal'),
                          'pa': score_decimal(stats, 'fpts_against', 'fpts_against_decimal')})
    standings.sort(key=lambda r: (-(r['wins']+.5*r['ties']), -r['pf'], r['roster_id']))
    for rank, row in enumerate(standings, 1):
        row['provisional_rank'] = rank
    if not isinstance(bracket, list) or not bracket:
        raise ValueError('Missing playoff bracket')
    matches = {m.get('m'): m for m in bracket}
    if len(matches) != len(bracket) or any(not isinstance(m, int) for m in matches):
        raise ValueError('Invalid bracket matches')
    first_round = [m for m in bracket if m.get('r') == 1]
    if len(first_round) != 2:
        raise ValueError('Expected two first-round games for six-team bracket')
    for match in bracket:
        for side in ('t1', 't2'):
            if match.get(side) is not None and match[side] not in ids:
                raise ValueError('Unknown bracket roster')
            origin = match.get(side+'_from')
            if origin:
                if not isinstance(origin, dict) or len(origin) != 1 or next(iter(origin)) not in ('w', 'l'):
                    raise ValueError('Invalid bracket origin')
                predecessor = matches.get(next(iter(origin.values())))
                if not predecessor or predecessor.get('r', 999) >= match.get('r', 0):
                    raise ValueError('Invalid bracket predecessor')
    bye_ids = sorted({m[s] for m in bracket if m.get('r') == 2 and not m.get('p')
                      for s in ('t1', 't2') if m.get(s) is not None and not m.get(s+'_from')})
    if len(bye_ids) != 2:
        raise ValueError('Expected two provisional bye teams')
    return {
        'schemaVersion': 80, 'module': 'private_league_reconstruction',
        'generatedAt': datetime.now(timezone.utc).isoformat(),
        'season': int(league['season']), 'week': _int(nfl.get('week'), 'week', 1),
        'standings': standings,
        'standings_order': 'PROVISIONAL wins+0.5*ties, PF; official tiebreak confirmation missing',
        'lineup': {'starters': STARTERS, 'bench': 5, 'reserve': 1},
        'rules': {k: settings.get(k) for k in ('trade_deadline', 'trade_review_days', 'waiver_type',
                    'waiver_day_of_week', 'waiver_clear_days', 'reserve_allow_out',
                    'reserve_allow_doubtful', 'reserve_allow_sus', 'reserve_allow_na', 'reserve_allow_dnr')},
        'deadline_semantics': 'trade_deadline is a week setting; exact local cutoff and processing eligibility require UI/rules confirmation',
        'playoffs': {'teams': 6, 'start_week': 15, 'first_round_matches': 2,
                     'provisional_bye_roster_ids': bye_ids, 'bracket': bracket,
                     'status': 'PROVISIONAL_BEFORE_REGULAR_SEASON_END; no berth or bye is clinched by this snapshot'},
        'scoring': scoring_compatibility(league.get('scoring_settings')),
        'championship': {'status': 'INSUFFICIENT_DATA', 'probability': None,
                         'missing': ['Official standings tiebreak confirmation',
                                     'Calibrated future nine-player score distributions including K/DEF',
                                     'Availability and same-game dependence models',
                                     'Remaining schedule reconstruction and sensitivity evaluation']},
        'private_operations': 'NOT_ACCESSED: pending waivers, trade offers and Trade Block are absent from the public API',
    }


def write_private_report(path, report):
    path = Path(path).resolve()
    # The execution host may itself be a managed git workspace. Protect the
    # actual public project rather than forbidding every sibling private path.
    public_project = Path(__file__).resolve().parent
    if path == public_project or public_project in path.parents:
        raise ValueError('Private league report cannot be written inside the public project')
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2)+'\n')
    temp.replace(path)
