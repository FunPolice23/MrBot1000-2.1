import sys
sys.path.insert(0, '.')
from agents import fact_ledger, evidence

L = fact_ledger.FactLedger(max_claims=200)
cid = L.record_claim("test subject", "a plain narration with no deterministic support", source="llm")
print("MB-QA-04 probe:")
print("  initial status:", L.get(cid).status, "evidence count:", len(L.get(cid).evidence))

e1 = evidence.Evidence(detail="tool output A", verification_level=evidence.VerificationLevel.L2_SUSPECT, method=evidence.VerificationMethod.AGENT_REPORT)
try:
    L.attach_evidence(cid, e1)
    print("  after e1:", L.get(cid).status, "evidence count:", len(L.get(cid).evidence))
except Exception as ex:
    print("  attach e1 CRASHED:", type(ex).__name__, str(ex)[:160])

e2 = evidence.Evidence(detail="tool output B", verification_level=evidence.VerificationLevel.L2_SUSPECT, method=evidence.VerificationMethod.AGENT_REPORT)
try:
    L.attach_evidence(cid, e2)
    print("  after e2 (same tier):", L.get(cid).status, "evidence count:", len(L.get(cid).evidence))
except Exception as ex:
    print("  attach e2 CRASHED:", type(ex).__name__, str(ex)[:160])
