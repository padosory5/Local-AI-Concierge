"""Agents: the helpers Noir works out with the user and runs.

    parts.py           what an agent can be made of (the catalog), and its card
    designer.py        the conversation in which an agent is worked out
    worker.py          the one step the built-in model takes for each file
    router.py          decides: chat, a helper to make or change, or a job for one
    builder.py         the plain questions, where no model can hold that conversation
    blueprints/*.yaml  what the plain questions ask
    blueprint.py       loads them
    planner.py         judges an idea by the building blocks it needs (capabilities.yaml)
    recipe.py          runs an agent that works on text
    runner.py          runs the agent that answers from a folder's documents
    files.py           reads files of every kind; keyword search
    store.py           saved agents
    starters.py        ready-made agents (starters.yaml)
    community.py       agents people share (community.json)
"""
