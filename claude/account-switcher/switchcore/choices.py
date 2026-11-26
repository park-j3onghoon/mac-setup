"""Look up the built-in implementation a local setting names. Only names in the given table can be
chosen: both switchers hold two accounts' tokens, so a setting never loads code from outside the repo.
Each kind keeps its table beside its implementations (POLICIES in policy.py), so a turn-end hook that
picks a terminal does not load the switching rules."""

from .cmux import CmuxTerminal


TERMINALS = {'cmux': CmuxTerminal}


def pick(kind, name, choices):
    """The class a local setting names; ValueError tells which names the setting could use."""
    if not isinstance(name, str) or name not in choices:
        raise ValueError(f'Invalid switcher setting: {kind}={name} (choose from: {", ".join(choices)})')
    return choices[name]
