"""AgentOps AUTO/MANUAL Runtime Loop (AGE-30).

Current task-mode runtime per docs/governance/CURRENT_RUNTIME_RULES.md.

No LOW/MEDIUM/HIGH risk classifier participates in the main control flow.
The loop is: Linear task (AUTO|MANUAL) -> Builder -> GitHub -> GPT review;
CHANGES_REQUESTED/NOT_PASS -> Builder fixes -> new code HEAD -> review again;
PASS -> continue in scope until acceptance criteria are satisfied.

Delivery is fail-closed: unconfirmed send/read-back is DELIVERY_FAILED.
The Controller terminates only on accepted completion, closure, or
cancellation.
"""
