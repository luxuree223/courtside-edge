"""Deterministic price math, separate from forecasting and recommendation decisions."""
import math
from . import markets

def expected_value(win_probability,american,stake=10,push_probability=0):
    """Net dollars, including pushes. Caller must supply an independently supported forecast.

    This helper is deliberately not exposed as an AI tool: the model cannot invent
    its own probability and ask the calculator to certify it as a betting edge.
    """
    if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in (win_probability,push_probability,stake)):
        raise ValueError('Use finite probabilities and stake.')
    if min(win_probability,push_probability)<0 or win_probability+push_probability>1 or stake<=0:raise ValueError('Invalid probabilities or stake.')
    return stake*(win_probability*(markets.decimal_odds(markets.valid_odds(american))-1)-(1-win_probability-push_probability))

def fair_american(win_probability,push_probability=0):
    if not 0<win_probability<1 or not 0<=push_probability<1 or win_probability+push_probability>=1:raise ValueError('A nonzero win and loss probability is required.')
    p=win_probability/(1-push_probability)
    return 100*(1-p)/p if p<=.5 else -100*p/(1-p)
