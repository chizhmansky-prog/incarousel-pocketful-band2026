# Independent black-box checks

These tests reset ONLY disposable challenge fixture instances. Never point them
at a real service or user data. They require two Stage4 instances and a separate
Stage3 donor. For `probe_pocketful_adversarial.py`, set POCKETFUL_BASE_URL,
POCKETFUL_IMPORT_URL, POCKETFUL_OLD_URL, POCKETFUL_REVISION (the tested Git revision)
and POCKETFUL_EVIDENCE_OUT (a fresh output directory), then run with Python3.
The standalone type-collision probe uses POCKETFUL_BASE_URL, POCKETFUL_REVISION
and POCKETFUL_EVIDENCE_OUT.
Both return a nonzero process status on an observed failure. They do not persist
credentials or raw exported states. All supplied values are challenge fixtures.
Source/served-asset binding and isolated published execution were performed
separately; these portable probes alone do not verify those boundaries.
