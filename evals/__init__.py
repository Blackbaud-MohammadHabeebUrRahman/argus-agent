"""Eval harness for the investigation agent.

The point: an LLM-powered agent is only trustworthy when you can prove
how often it reaches the right conclusion on known-answer cases. This
package runs the agent against hand-crafted scenarios with mocked tool
responses, grades the output deterministically plus with an LLM judge,
and emits a report so a change to the prompt, model, or tool set can be
scored before it ships.
"""
