from pathlib import Path
import hashlib
root=Path(__file__).resolve().parent
expected={"publish_git.original.py":"30e3386a6ee36daaa98efc31a2ea0e26ea0988dfb474fa35066d5988ed4a7695","publish_git.py":"fa71c3a097973600038579ccbedaec27a19bb6b6b5171a72049d916afbb4fcad","tests/test_publish_git.py":"ca5965a4a5008e5847293f79d53b81028c3748285d4a4fac74b3298e2ffe2c38","tests/test_publisher_timeout.py":"1ff76b5c790618f1484da016bc0b7c7dca16015472f0c1624b26638e7885b50b","test_partial_clone.py":"aebe81347d0b473f7161ae2e10286699804161075d1f8a882d32ff2b504f588d","run_ci.sh":"f74eee9d1541fa7d30d74c9f7c67c2881960edd3dd73df0ca150ee23068f0131"}
for rel,digest in expected.items():
    if hashlib.sha256((root/rel).read_bytes()).hexdigest()!=digest:
        raise RuntimeError("SOURCE_TEST_INPUT_HASH_MISMATCH:"+rel)
print("PASS_EXACT_SIX_INPUTS")
