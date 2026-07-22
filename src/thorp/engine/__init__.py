"""Trading engine safety core: RiskEngine + OMS (Docs 3-4).

This is the code the adversarial reviews found the worst bugs in, so it is built
to the revised design: the in-flight exposure reservation ledger (Doc 3 §3.5,
Doc 4 §2), the revised OMS state machine with PENDING_CANCEL (Doc 3 §3.6), and
fade/cap enforcement that never trusts the strategy layer (Doc 4 §2). Every
control has a negative test (Doc 6 §2).
"""
