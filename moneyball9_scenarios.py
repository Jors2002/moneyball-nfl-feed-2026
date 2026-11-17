"""Exact regular-season rank bounds under binary game outcomes. No odds assigned."""
import numpy as np


def rank_bounds(wins, games, team):
    """Ties in final standings may break either way. Matchup ties are excluded."""
    if team not in wins or any(type(v) is not int or v < 0 for v in wins.values()):
        raise ValueError("Nonnegative integer starting wins required")
    if len(games) > 22:
        raise ValueError("Exact enumeration supports at most 22 remaining games")
    ids = list(wins)
    fixtures = []
    for a, b in games:
        if a == b or a not in wins or b not in wins:
            raise ValueError("Invalid matchup")
        fixtures.append((ids.index(a), ids.index(b)))
    baseline = np.array(list(wins.values()), dtype=int)
    target = ids.index(team)
    bounds = {}
    for start in range(0, 1 << len(games), 8192):
        outcomes = np.arange(start, min(start + 8192, 1 << len(games)))
        final = np.tile(baseline, (len(outcomes), 1))
        for bit, (a, b) in enumerate(fixtures):
            second = (outcomes >> bit) & 1
            final[:, a] += 1 - second
            final[:, b] += second
        own = final[:, target, None]
        best = 1 + (final > own).sum(axis=1)
        worst = (final >= own).sum(axis=1)
        for total in np.unique(own):
            mask = own[:, 0] == total
            low, high = bounds.get(int(total), (len(ids), 1))
            bounds[int(total)] = (min(low, int(best[mask].min())),
                                  max(high, int(worst[mask].max())))
    return dict(sorted(bounds.items()))
