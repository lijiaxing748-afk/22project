#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
把工作区里"已跟踪的文本文件"统一成 LF 换行，以便提交。

为什么需要这个脚本：
  Windows 上 core.autocrlf=true 时，git 认为"工作区是 CRLF、仓库是 LF"才算正常，
  所以 `git add --renormalize` 会报告"无需变更"——但仓库里的 blob 其实带着 CRLF。
  对 .sh / .service 这类要拷到 Linux 执行的文件，CRLF 会让 shebang 变成
  `#!/usr/bin/env bash\r`，运行时报 `/usr/bin/env: 'bash\r': No such file or directory`
  （等价于 systemd 的 203/EXEC）。

  本脚本不依赖 git 的判断，直接把文件字节里的 CRLF 改成 LF，
  只处理"文本类"扩展名，二进制文件（图片/权重/办公文档）原样跳过。

用法：
    python tools/normalize-eol.py [--check] [目录 ...]

    --check   只报告哪些文件需要转换，不修改
"""
import argparse
import sys
from pathlib import Path

# 需要强制 LF 的文本扩展名（与 .gitattributes 保持一致）
LF_EXTS = {
    ".sh", ".bash", ".service", ".conf", ".env", ".properties",
    ".py", ".txt", ".md", ".json", ".yml", ".yaml", ".sql",
    ".ts", ".js", ".vue", ".html", ".css", ".scss",
    ".cfg", ".ini", ".toml", ".in", ".example",
    ".bat", ".cmd", ".ps1",  # Windows 脚本也统一，避免 diff 噪音
}

# 明确跳过：二进制 / 办公文档 / 模型产物
SKIP_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp", ".svg",
    ".ttf", ".woff", ".woff2", ".eot",
    ".zip", ".gz", ".tar", ".7z", ".rar",
    ".exe", ".dll", ".so", ".pyd",
    ".docx", ".xlsx", ".pptx", ".pdf",
    ".mat", ".npy", ".npz", ".pkl", ".pt", ".pth", ".keras", ".h5", ".onnx",
    ".iso", ".vmdk", ".vdi",
    ".db", ".sqlite", ".sqlite3",
}

SKIP_DIRS = {
    ".git", "node_modules", "venv", ".venv", "__pycache__",
    "dist", "dist-linux", ".idea", ".vscode", "build", "out", ".cache",
}


def is_lf_text(path: Path) -> bool:
    ext = path.suffix.lower()
    if ext in SKIP_EXTS:
        return False
    if ext in LF_EXTS:
        return True
    if not ext and path.name.lower() in {"dockerfile", "makefile", "procfile", "dockerfile".lower()}:
        return True
    return False


def iter_targets(roots):
    for root in roots:
        root = Path(root)
        if root.is_file():
            yield root
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            if is_lf_text(p):
                yield p


def normalize(path: Path, check: bool) -> bool:
    """返回 True 表示该文件含 CRLF（需要或已经修复）。"""
    data = path.read_bytes()
    if b"\r\n" not in data:
        return False
    if check:
        return True
    # 只替换 CRLF；单独的 CR 不动（极少见，避免误伤）
    path.write_bytes(data.replace(b"\r\n", b"\n"))
    return True


def main():
    ap = argparse.ArgumentParser(description="把文本文件的 CRLF 统一为 LF")
    ap.add_argument("roots", nargs="*", default=["."], help="要处理的目录或文件")
    ap.add_argument("--check", action="store_true", help="只检查不修改")
    args = ap.parse_args()

    roots = args.roots or ["."]
    changed, scanned = [], 0
    for p in iter_targets(roots):
        scanned += 1
        try:
            if normalize(p, args.check):
                changed.append(p)
        except OSError as e:
            print(f"  跳过 {p}: {e}", file=sys.stderr)

    verb = "需要转换" if args.check else "已转换为 LF"
    print(f"扫描 {scanned} 个文本文件，{len(changed)} 个{verb}")
    for p in changed[:80]:
        print(f"  {p}")
    if len(changed) > 80:
        print(f"  ... 另有 {len(changed) - 80} 个")

    if args.check and changed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
