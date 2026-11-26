"""The built-in implementations a local setting may name. Only names listed here can be chosen:
both switchers hold two accounts' tokens, so a setting never loads code from outside the repo."""

from .policy import PriorityPolicy


POLICIES = {'priority': PriorityPolicy}
CHOICES = {'policy': POLICIES}


def pick(kind, name):
    """The class a local setting names; ValueError tells which names the setting could use."""
    choices = CHOICES[kind]
    if not isinstance(name, str) or name not in choices:
        raise ValueError(f'Invalid switcher setting: {kind}={name} (choose from: {", ".join(choices)})')
    return choices[name]
