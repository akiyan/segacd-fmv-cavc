"""Hold the project's managed fixture lease for a browser comparison run."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'tools'))
from tmpfs_workspace import lease_managed_path
leases=[lease_managed_path(Path(value)) for value in sys.argv[1:]]
try:
    print('LEASE_READY',flush=True)
    sys.stdin.read()
finally:
    for lease in leases:
        if lease:lease.release()
