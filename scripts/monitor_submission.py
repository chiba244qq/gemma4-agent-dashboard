import time
import subprocess
import json
import sys

TARGET_REF = "58145086"

def get_submission_status(ref):
    cmd = ["/Users/echo/anaconda3/bin/kaggle", "competitions", "submissions", "-c", "gemma-4-developer-agent"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    for line in res.stdout.splitlines():
        if ref in line:
            parts = line.split()
            for i, p in enumerate(parts):
                if p.startswith("SubmissionStatus."):
                    status = p
                    score = parts[i+1] if i+1 < len(parts) and parts[i+1] != "None" else None
                    return status, score
    return None, None

print(f"Monitoring submission {TARGET_REF}...")
while True:
    status, score = get_submission_status(TARGET_REF)
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Status: {status}, Score: {score}", flush=True)
    if status == "SubmissionStatus.COMPLETE":
        print(f"Target {TARGET_REF} COMPLETE! Public Score: {score}")
        subprocess.run([sys.executable, "/Users/echo/kaggle/gemma4-agent-dashboard/scripts/update_dashboard.py"])
        break
    elif status in ["SubmissionStatus.ERROR", "SubmissionStatus.FAILED"]:
        print(f"Target {TARGET_REF} finished with error: {status}")
        subprocess.run([sys.executable, "/Users/echo/kaggle/gemma4-agent-dashboard/scripts/update_dashboard.py"])
        break
    time.sleep(60)
