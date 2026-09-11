#!/usr/bin/env python3
"""Small CLI/GUI helper for publishing the safe GitHub mirror.

Examples:
    python scripts/github_upload.py status
    python scripts/github_upload.py publish -m "Update public mirror"
    python scripts/github_upload.py workflow
    python scripts/github_upload.py --gui

Set MRBOT_SOURCE_DIR when this script is run from D:\\github_upload and the
source checkout is somewhere else. Set GITHUB_UPLOAD_DIR to override the
mirror location.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk


DEFAULT_SOURCE = Path(r"D:\MrBot1000_2.0")
DEFAULT_UPLOAD = Path(r"D:\github_upload")
REMOTE_URL = "https://github.com/FunPolice23/MrBot1000-2.1.git"
WORKFLOW_HELP = """MrBot1000 GitHub publishing workflow

Normal first-time or repeat workflow:
    1. status   Check the mirror and confirm the remote repository.
    2. pull     Get remote commits first, if the mirror is clean.
    3. sync     Copy the safe source files into the mirror.
    4. diff     Review the changed-file summary.
    5. commit   Save the reviewed changes locally in the mirror.
    6. push     Send the commit to GitHub.

The GUI buttons perform these same actions. Publish is a shortcut for sync,
commit, and push. Use Pull before Publish when other commits may exist online.
Pull, push, and publish ask for confirmation before contacting GitHub.

The source checkout is D:\\MrBot1000_2.0 and the public Git mirror is
D:\\github_upload. The source-to-mirror copy engine is kept in
scripts/sync_github_upload.py; normally you use only github_upload.py.
"""


def source_dir() -> Path:
    configured = os.getenv("MRBOT_SOURCE_DIR", "").strip()
    if configured:
        return Path(configured).resolve()
    here = Path(__file__).resolve().parents[1]
    if here != upload_dir() and (here / "main.py").exists():
        return here
    return DEFAULT_SOURCE


def upload_dir() -> Path:
    return Path(os.getenv("GITHUB_UPLOAD_DIR", str(DEFAULT_UPLOAD))).resolve()


def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    repo = upload_dir()
    if not (repo / ".git").is_dir():
        raise RuntimeError(f"Git repository not found: {repo}")
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return result


def sync_source() -> str:
    script = source_dir() / "scripts" / "sync_github_upload.py"
    if not script.is_file():
        raise RuntimeError(f"Sync script not found: {script}")
    env = os.environ.copy()
    env["GITHUB_UPLOAD_DIR"] = str(upload_dir())
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(source_dir()),
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    output = (result.stdout + result.stderr).strip()
    if result.returncode:
        raise RuntimeError(output or "Synchronization failed")
    return output or "Synchronization complete."


def ensure_remote() -> str:
    actual = run_git("remote", "get-url", "origin").stdout.strip()
    if actual != REMOTE_URL:
        raise RuntimeError(
            f"origin is {actual!r}, expected {REMOTE_URL!r}; refusing to publish")
    return actual


def status_text() -> str:
    ensure_remote()
    result = run_git("status", "--short", "--branch")
    return result.stdout.strip() or "Working tree is clean."


def diff_text() -> str:
    ensure_remote()
    result = run_git("diff", "--stat")
    return result.stdout.strip() or "No unstaged diff."


def commit(message: str) -> str:
    ensure_remote()
    status = run_git("status", "--porcelain").stdout.strip()
    if not status:
        return "Nothing to commit."
    if not message.strip():
        raise ValueError("A commit message is required")
    run_git("add", "-A")
    result = run_git("commit", "-m", message.strip())
    return result.stdout.strip()


def pull() -> str:
    ensure_remote()
    return run_git("pull", "--ff-only").stdout.strip() or "Already up to date."


def push() -> str:
    ensure_remote()
    return run_git("push").stdout.strip() or "Push complete."


def publish(message: str, pull_first: bool = False) -> str:
    parts = []
    if pull_first:
        parts.append(pull())
    parts.append(sync_source())
    parts.append(commit(message))
    parts.append(push())
    return "\n".join(part for part in parts if part)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gui", action="store_true", help="Open the simple desktop workflow")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("workflow", help="Show the recommended publishing order")
    sub.add_parser("sync", help="Copy the safe source mirror")
    sub.add_parser("status", help="Show mirror Git status")
    sub.add_parser("diff", help="Show the unstaged diff summary")
    pull_cmd = sub.add_parser("pull", help="Fast-forward the mirror from origin")
    pull_cmd.add_argument("--yes", action="store_true", help="Skip confirmation")
    commit_cmd = sub.add_parser("commit", help="Commit current mirror changes")
    commit_cmd.add_argument("-m", "--message", required=True)
    push_cmd = sub.add_parser("push", help="Push committed mirror changes")
    push_cmd.add_argument("--yes", action="store_true", help="Skip confirmation")
    pub_cmd = sub.add_parser("publish", help="Sync, commit, and push the mirror")
    pub_cmd.add_argument("-m", "--message", required=True)
    pub_cmd.add_argument("--pull-first", action="store_true")
    pub_cmd.add_argument("--yes", action="store_true", help="Skip confirmation")
    return parser


def run_cli(args: argparse.Namespace) -> int:
    if args.command in {"push", "publish"} and not args.yes:
        answer = input("This will contact GitHub. Continue? [y/N] ").strip().lower()
        if answer != "y":
            print("Canceled.")
            return 0
    if args.command == "workflow":
        print(WORKFLOW_HELP)
    elif args.command == "sync":
        print(sync_source())
    elif args.command == "status":
        print(status_text())
    elif args.command == "diff":
        print(diff_text())
    elif args.command == "pull":
        if not args.yes and input("Pull with --ff-only? [y/N] ").strip().lower() != "y":
            print("Canceled.")
            return 0
        print(pull())
    elif args.command == "commit":
        print(commit(args.message))
    elif args.command == "push":
        print(push())
    elif args.command == "publish":
        print(publish(args.message, args.pull_first))
    else:
        build_parser().print_help()
    return 0


def launch_gui() -> None:
    root = tk.Tk()
    root.title("MrBot1000 GitHub Upload")
    root.geometry("760x500")
    output = tk.Text(root, height=22, width=100, state="disabled")
    output.pack(fill="both", expand=True, padx=10, pady=10)

    def show(text: str) -> None:
        output.configure(state="normal")
        output.insert("end", text + "\n\n")
        output.see("end")
        output.configure(state="disabled")

    def action(fn) -> None:
        try:
            show(fn())
        except Exception as exc:
            show(f"ERROR: {exc}")
            messagebox.showerror("GitHub upload", str(exc))

    bar = ttk.Frame(root)
    bar.pack(fill="x", padx=10, pady=(0, 10))
    ttk.Button(bar, text="Help", command=lambda: show(WORKFLOW_HELP)).pack(side="left")
    ttk.Button(bar, text="Sync Source", command=lambda: action(sync_source)).pack(side="left")
    ttk.Button(bar, text="Status", command=lambda: action(status_text)).pack(side="left", padx=4)
    ttk.Button(bar, text="Diff", command=lambda: action(diff_text)).pack(side="left", padx=4)

    def commit_gui() -> None:
        message = simpledialog.askstring("Commit", "Commit message:", parent=root)
        if message:
            action(lambda: commit(message))

    def publish_gui() -> None:
        message = simpledialog.askstring("Publish", "Commit message:", parent=root)
        if not message:
            return
        if messagebox.askyesno("Confirm publish", "Sync, commit, and push to GitHub?", parent=root):
            action(lambda: publish(message))

    def pull_gui() -> None:
        if messagebox.askyesno("Confirm pull", "Fast-forward the mirror from GitHub?", parent=root):
            action(pull)

    ttk.Button(bar, text="Pull", command=pull_gui).pack(side="left", padx=4)
    ttk.Button(bar, text="Commit", command=commit_gui).pack(side="left", padx=4)
    ttk.Button(bar, text="Publish", command=publish_gui).pack(side="left", padx=4)
    show(f"Source: {source_dir()}\nUpload repo: {upload_dir()}\nRemote: {REMOTE_URL}")
    root.mainloop()


if __name__ == "__main__":
    parser = build_parser()
    parsed = parser.parse_args()
    if parsed.gui or parsed.command is None:
        launch_gui()
    else:
        try:
            raise SystemExit(run_cli(parsed))
        except (RuntimeError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            raise SystemExit(1)
