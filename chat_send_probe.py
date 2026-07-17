import sys, urllib.request, json, time
t = time.time()
try:
    req = urllib.request.Request(
        "http://127.0.0.1:7890/api/chat/send",
        data=json.dumps({"text": "verify batch4 ping"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    r = urllib.request.urlopen(req, timeout=60)
    print(f"took {round(time.time()-t, 1)}s")
    print(r.status)
    body = r.read().decode()
    print(body[:300])
except Exception as e:
    print(f"took {round(time.time()-t, 1)}s")
    print("ERR:", repr(e), file=sys.stderr)
    sys.exit(1)
