import os

repo_dir = "."
output_file = "all_codebase.txt"
ignore_ext = {".db", ".pyc", ".png", ".env", ".jpg", ".zip", ".tar", ".gz", ".DS_Store"}
ignore_dirs = {".git", "__pycache__", ".venv", "venv", ".idea", ".vscode"}

with open(output_file, "w", encoding="utf-8") as out:
    for root, dirs, files in os.walk(repo_dir):
        # Skip ignored directories
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        for f in sorted(files):
            if f in ("bundle.py", output_file):
                continue
            path = os.path.join(root, f)
            if any(path.endswith(ext) for ext in ignore_ext):
                continue
            try:
                with open(path, "r", encoding="utf-8") as file_content:
                    divider = "=" * 50
                    out.write(f"\n{divider}\nFILE: {path}\n{divider}\n\n")
                    out.write(file_content.read())
                    out.write("\n")
            except Exception:
                pass

print(f"Combined codebase successfully saved to '{output_file}'")
