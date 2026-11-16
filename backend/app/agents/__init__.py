"""AgentState, orchestrator and agents over LangGraph (plan §3.4, §8.1).

Implemented: typed `AgentState` (`state`); intent templates (`intents`); the bounded tools behind
`call_tool` (`tools`); the cited answer — evidence package → model → citation check (`answer`,
ADR-0024); the conversation as a LangGraph graph over `AgentState`, one run per turn with session
memory, scoped answer cache and query log (`orchestrator`, ADR-0029); the e-Office touchpoints
(`routes`, `first_cut`, `dfa`, `brief`, `receipts`, `local_reference`).
"""
