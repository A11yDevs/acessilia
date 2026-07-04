import os, re, sys
matches = []
for root, dirs, files in os.walk('.'):
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            with open(path, 'r', encoding='utf-8') as fh:
                for i, line in enumerate(fh, 1):
                    if re.search(r'def\s+is_file_size_allowed\s*\(', line):
                        matches.append((path, i, line.strip()))
for m in matches:
    print(m)
