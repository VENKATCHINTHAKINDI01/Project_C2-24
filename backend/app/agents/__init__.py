"""AgentState, orchestrator and agents over LangGraph (plan §3.4, §8.1).

Implemented: typed `AgentState` with cross-field consistency checks (`state`); intent templates —
intent + validated slots → fixed `LadderRequest` (`intents`); the six bounded tools of plan §5.6
behind one validated entry point `call_tool` (`tools`). Not yet: LangGraph graph, Gemini
intent classification and drafting (needs GCP), agents.
"""
