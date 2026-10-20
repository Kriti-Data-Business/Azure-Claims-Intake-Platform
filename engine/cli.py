import json, sys
from engine.audit import AuditLog
from engine.pack import load_pack
from engine.pipeline import run

if __name__ == "__main__":
    pack = load_pack(sys.argv[1])
    print(json.dumps(run(open(sys.argv[2]).read(), pack, AuditLog()), indent=2))
