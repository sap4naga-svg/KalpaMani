"""Gold curation: point-in-time research artifacts.

Gold holds **raw** bars, corporate actions, historical universes and the keyed
adjusted-bar cache artifacts. It never holds an adjusted series that is not keyed
by its adjustment policy, resolved profile, ``as_of`` epoch and input dataset
versions.

Research, strategy, risk and portfolio code may not import this package.
"""
