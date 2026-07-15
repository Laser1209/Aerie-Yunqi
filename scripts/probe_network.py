"""Network reachability probe with hard 8s timeout per host."""
import socket
import time

hosts = [
    ("api.openai.com", 443),
    ("api.deepseek.com", 443),
    ("api.minimaxi.com", 443),
    ("open.bigmodel.cn", 443),
    ("api.siliconflow.cn", 443),
    ("dashscope.aliyuncs.com", 443),
    ("generativelanguage.googleapis.com", 443),
]

for host, port in hosts:
    t0 = time.perf_counter()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    try:
        s.connect((host, port))
        dt = time.perf_counter() - t0
        print(f"OK    {host:40s}:{port}  reachable in {dt:.2f}s", flush=True)
    except socket.timeout:
        dt = time.perf_counter() - t0
        print(f"TIMEOUT {host:40s}:{port}  {dt:.2f}s (likely blocked/firewalled)", flush=True)
    except Exception as e:
        dt = time.perf_counter() - t0
        print(f"FAIL  {host:40s}:{port}  {type(e).__name__}: {e}", flush=True)
    finally:
        s.close()
