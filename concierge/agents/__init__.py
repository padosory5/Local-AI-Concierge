"""Agents: blueprint-based helpers that Noir creates with the user and runs.

    blueprints/*.yaml  the tested agent templates (the menu)
    blueprint.py       loads them
    router.py          decides: chat, create an agent, or run one
    builder.py         interview, agent card, create with a test drive
    files.py           reads PDF, Word and text files; keyword search
    store.py           saved agents
    runner.py          runs an agent on a request
"""
