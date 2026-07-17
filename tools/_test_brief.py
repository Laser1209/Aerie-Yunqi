import urllib.request, json, time, sys
sys.stdout.reconfigure(encoding="utf-8")
t0 = time.time()
r = urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:7890/api/brief/run", method="POST"), timeout=60)
body = json.loads(r.read().decode("utf-8"))
print(f"elapsed: {time.time()-t0:.1f}s")
b = body.get("brief", {})
print("errors:", b.get("errors"))
print("counts:")
for k, v in b.items():
    if k in ("date", "ts", "markdown"):
        continue
    if isinstance(v, list):
        print(f"  {k} = {len(v)}")
    else:
        print(f"  {k} = {1 if v else 0}")
