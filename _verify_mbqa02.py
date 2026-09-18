import sys
sys.path.insert(0, '.')
from agents import safety_gate

g = safety_gate.SafetyGate(auto_approve_readonly=False)
s1, n1, d1 = g.check("opportunity_portfolio.list_open")
print("MB-QA-02 probe:")
print("  READONLY under False ->", repr(s1), repr(d1))
s2, n2, d2 = g.check("opportunity_portfolio.approve")
print("  APPROVE  under False ->", repr(s2), repr(d2))
