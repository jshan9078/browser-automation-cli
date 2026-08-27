#!/usr/bin/env python3
"""Load BU Bench V1 tasks (browser-use/benchmark). The set is base64+Fernet with a PUBLIC key
(sha256("BU_Bench_V1")) — that's their intended run mechanism. Do NOT commit decrypted task text
(their request: don't publish plaintext / don't train on it). raw/ and results/ are gitignored.

  loader.py count            -> total + per-category counts
  loader.py ids [category]   -> task_ids (optionally filtered)
  loader.py get <task_id>    -> one task as JSON (used by run_task.py)
"""
import base64, hashlib, json, sys, collections
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENC = HERE / "BU_Bench_V1.enc"


def load_tasks():
    from cryptography.fernet import Fernet
    key = base64.urlsafe_b64encode(hashlib.sha256(b"BU_Bench_V1").digest())
    enc = base64.b64decode(ENC.read_text())
    return json.loads(Fernet(key).decrypt(enc))


def _by_id(tid):
    return next((t for t in load_tasks() if t.get("task_id") == tid), None)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "count"
    tasks = load_tasks()
    if cmd == "count":
        print("total:", len(tasks))
        print("by category:", dict(collections.Counter(t.get("category") for t in tasks)))
    elif cmd == "ids":
        cat = sys.argv[2] if len(sys.argv) > 2 else None
        for t in tasks:
            if not cat or t.get("category") == cat:
                print(t["task_id"])
    elif cmd == "get":
        t = _by_id(sys.argv[2])
        print(json.dumps(t) if t else "")
