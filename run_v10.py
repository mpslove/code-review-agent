"""V10.1 Runner - fixed cross-category dedup bug"""
import os, sys, time, re, subprocess

key_path = "D:/security-agents/code-review-agent/.env.key"
with open(key_path) as f:
    key = f.read().strip()
os.environ['DEEPSEEK_API_KEY'] = key
print(f"Key loaded: {len(key)} chars")

base = "D:/security-agents/code-review-agent"
os.chdir(base)

outdir = "tests/benchmark/v10_dedup"
os.makedirs(outdir, exist_ok=True)

diff_dirs = ["tests/benchmark/real_prs", "tests/benchmark/new_prs"]
total = 0
start = time.time()

for ddir in diff_dirs:
    for fname in sorted(os.listdir(os.path.join(base, ddir))):
        if not fname.endswith('.diff'):
            continue
        pr_name = fname.replace('.diff', '')
        total += 1
        diff_path = os.path.join(ddir, fname)
        out = os.path.join(outdir, f"{pr_name}.md")

        print(f"\n{'='*50}\n[{total}/20] {pr_name}\n{'='*50}")

        cmd = [
            sys.executable, '-m', 'src.main',
            '--diff-file', diff_path,
            '--rounds', '2', '--min-consensus', '2',
            '--mode', 'balanced', '--runs', '2',
            '--output', out,
        ]
        result = subprocess.run(cmd, cwd=base, capture_output=True, text=True, timeout=600)
        lines = [l for l in (result.stdout + result.stderr).split('\n') if l.strip()]
        for line in lines[-3:]:
            print(f"  {line[:120]}")
        if result.returncode != 0:
            print(f"  WARNING: exit {result.returncode}")
            # Print the actual error
            for line in lines:
                if 'Error' in line or 'error' in line or 'KeyError' in line or 'Traceback' in line:
                    print(f"  ERR: {line[:150]}")

elapsed = time.time() - start
print(f"\n{'='*50}\nV10 Complete: {total} PRs in {int(elapsed/60)}m")

for fname in sorted(os.listdir(outdir)):
    if not fname.endswith('.md'): continue
    with open(os.path.join(outdir, fname), encoding='utf-8') as f:
        content = f.read()
    count = len(re.findall(r'\*\*\[(\w+)\]\*\*', content))
    print(f"  {fname.replace('.md','')}: {count}")
