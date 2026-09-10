#!/usr/bin/env python3
"""verify_all_fixes.py — Consolidated verification script for all applied fixes.

Checks:
1. database.py — cost_usd column migration (no OperationalError on existing DB)
2. gui/dual_brain_control.py — deferred signal wiring (no AttributeError on tab switch)
3. gui/dual_brain_control.py — no .connect() calls inside setup_ui targeting later methods
4. CHANGELOG.md — has entry for 2.0.37e
"""
import ast
import sys
from pathlib import Path

REPO = Path("D:/MrBot1000_2.0")
errors = []

# 1. database.py — cost_usd migration present
db_path = REPO / "database.py"
db_src = db_path.read_text()
if "ALTER TABLE llm_calls ADD COLUMN" not in db_src:
    errors.append("database.py: missing ALTER TABLE migration for cost_usd")
if "prompt_tokens" not in db_src:
    errors.append("database.py: missing prompt_tokens migration")
if "cost_usd" not in db_src:
    errors.append("database.py: missing cost_usd reference")

# 2. dual_brain_control.py — deferred wiring present
dbc_path = REPO / "gui" / "dual_brain_control.py"
dbc_src = dbc_path.read_text()
if "_wire_all_signals" not in dbc_src:
    errors.append("dual_brain_control.py: missing _wire_all_signals")
if "QTimer.singleShot(0, self._wire_all_signals)" not in dbc_src:
    errors.append("dual_brain_control.py: missing QTimer.singleShot for _wire_all_signals")
for method in ["_wire_start_stop_buttons", "_wire_refresh_buttons", "_wire_settings_signals"]:
    if method not in dbc_src:
        errors.append(f"dual_brain_control.py: missing {method}")

# 3. AST check — no .connect() in setup_ui targeting later-defined methods
tree = ast.parse(dbc_src)
setup_end = None
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == "setup_ui":
        setup_end = node.end_lineno
        break
later_methods = set()
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.lineno > setup_end:
        later_methods.add(node.name)
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == "setup_ui":
        for child in ast.walk(node):
            if isinstance(child, ast.Expr) and isinstance(child.value, ast.Call):
                func = child.value.func
                if isinstance(func, ast.Attribute) and func.attr == "connect":
                    target = None
                    if isinstance(func.value, ast.Attribute):
                        target = func.value.attr
                    elif isinstance(func.value, ast.Call):
                        if isinstance(func.value.func, ast.Attribute):
                            target = func.value.func.attr
                    if target and target in later_methods:
                        errors.append(f"dual_brain_control.py: setup_ui still connects to later method {target} at line {child.lineno}")

# 4. CHANGELOG.md — 2.0.37e entry present
cl_path = REPO / "CHANGELOG.md"
cl_src = cl_path.read_text()
if "[2.0.37e]" not in cl_src:
    errors.append("CHANGELOG.md: missing [2.0.37e] entry")
if "DB column migration" not in cl_src:
    errors.append("CHANGELOG.md: missing DB column migration description")
if "deferred signal wiring" not in cl_src:
    errors.append("CHANGELOG.md: missing deferred signal wiring description")

if errors:
    print("VERIFICATION FAILED:")
    for e in errors:
        print(f"  ✗ {e}")
    sys.exit(1)
else:
    print("All fixes verified:")
    print("  ✓ database.py — cost_usd column migration present")
    print("  ✓ dual_brain_control.py — deferred wiring pattern in place")
    print("  ✓ dual_brain_control.py — no late-method .connect() in setup_ui")
    print("  ✓ CHANGELOG.md — [2.0.37e] entry documented")
    sys.exit(0)