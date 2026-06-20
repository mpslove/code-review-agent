"""Helper to run agent with API key from Hermes .env"""
import os, sys, subprocess

env_path = os.path.expandvars(r"%LOCALAPPDATA%\hermes\.env")
key = ""
with open(env_path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line.startswith("DEEPSEEK_API_KEY=***            key = line.split("=", 1)[1].strip().strip('"').strip("'")
            break

if not key:
    print("ERROR: DEEPSEEK_API_KEY not found in .env")
    sys.exit(1)

os.environ["DEEPSEEK_API_KEY"] = key

# Use the venv python
venv_python = os.path.expandvars(r"%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe")
cmd = [venv_python] + sys.argv[1:]
print(f"Running with key={len(key)} chars...")
result = subprocess.run(cmd, env=os.environ)
sys.exit(result.returncode)
