## LangGraph Anti-Patterns
* **Never mutate state lists in-place:** When reading list/dict values from a LangGraph state dictionary inside a node, always create a copy (e.g., `list(state.get("key", []))`) before appending or modifying. In-place mutation corrupts the state during retry loops and causes duplicate accumulation.
