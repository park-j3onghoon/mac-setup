"""The built-in implementations a local setting may name. Only names listed here can be chosen:
both switchers hold two accounts' tokens, so a setting never loads code from outside the repo."""

from .cmux import CmuxTerminal
from .policy import PriorityPolicy, StrictPriorityPolicy


POLICIES = {'priority': PriorityPolicy, 'strict-priority': StrictPriorityPolicy}
TERMINALS = {'cmux': CmuxTerminal}
CHOICES = {'policy': POLICIES, 'terminal': TERMINALS}


def pick(kind, name):
    """The class a local setting names; ValueError tells which names the setting could use."""
    choices = CHOICES[kind]
    if not isinstance(name, str) or name not in choices:
        raise ValueError(f'Invalid switcher setting: {kind}={name} (choose from: {", ".join(choices)})')
    return choices[name]
