#!/usr/bin/env python3
"""把本项目作为 DSH 插件装进某个 profile（等价于 dshmarket 那种“一条命令”装法）。

为什么不能只跑 `dsh plugin --profile web add <名字>`：
1. `dsh plugin --profile <name> <args>` 是 **pnpm 透传**（`dsh plugin --help` 打出来的就是 pnpm 的帮助），
   它只做「依赖解析 + 建立 node_modules 链接」；
2. DSH 启动时按 `package.json` 的 `dsh.profile.bundles` 顺序叠 patch 层
   （见 @deepseek-ai/dsh 的 profile-boot：*bundle layers in `dsh.profile.bundles` order*），
   **没进 bundles 的包不会被挂载**；
3. 本项目的两个插件是 `@local/*` 私有工作区包（`"private": true`），npm 上不存在，
   所以 `add @local/dsh-autolearn` 必然解析失败。

因此正确的两步是：
    dsh plugin --profile web add link:<插件绝对路径>   # 依赖 + 链接
    把包名写进 dsh.profile.bundles                     # 挂载
本脚本把这两步合成一条命令，并在最后用 --dump-config 自检。

用法：
    python3 scripts/install_plugin.py --profile web --dry-run
    python3 scripts/install_plugin.py --profile web
    python3 scripts/install_plugin.py --profile web --uninstall
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = ROOT / "plugins" / "art-uiux"
PACKAGE_NAME = "@local/art-uiux"


def profile_dir(name: str) -> Path:
    home = Path.home() / ".dsh" / "profiles" / name
    if not home.exists():
        raise SystemExit("找不到 profile: %s（可用 --from-default-profile 先创建）" % home)
    return home


def read_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def bundle_registered(doc: dict) -> bool:
    return PACKAGE_NAME in (doc.get("dsh", {}).get("profile", {}).get("bundles") or [])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="web")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要执行的动作")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--no-pnpm", action="store_true", help="跳过 pnpm 步骤（仅维护 bundles 与链接）")
    args = ap.parse_args()

    pdir = profile_dir(args.profile)
    manifest = pdir / "package.json"
    doc = read_manifest(manifest)
    already_dep = PACKAGE_NAME in (doc.get("dependencies") or {})
    already_bundle = bundle_registered(doc)

    actions = []
    if args.uninstall:
        if already_bundle:
            actions.append("从 dsh.profile.bundles 移除 %s" % PACKAGE_NAME)
        actions.append("移除依赖与 node_modules 链接：dsh plugin --profile %s remove %s" % (args.profile, PACKAGE_NAME))
    else:
        if not already_dep:
            actions.append("dsh plugin --profile %s add link:%s" % (args.profile, PLUGIN_DIR))
        if not already_bundle:
            actions.append("把 %s 追加到 dsh.profile.bundles" % PACKAGE_NAME)
        if already_dep and already_bundle:
            actions.append("已安装且已登记，无需变更（幂等）")

    print("profile:", pdir)
    print("插件路径:", PLUGIN_DIR)
    for a in actions:
        print("  -", a)
    if args.dry_run:
        print("\n(dry-run，未做任何修改)")
        return 0

    backup = manifest.with_name("package.json.bak-install-%s" % datetime.now().strftime("%H%M%S"))
    shutil.copy2(manifest, backup)
    print("已备份:", backup.name)

    try:
        if not args.no_pnpm:
            verb = "remove" if args.uninstall else "add"
            spec = PACKAGE_NAME if args.uninstall else "link:%s" % PLUGIN_DIR
            subprocess.run(["dsh", "plugin", "--profile", args.profile, verb, spec], check=True)

        doc = read_manifest(manifest)
        bundles = doc.setdefault("dsh", {}).setdefault("profile", {}).setdefault("bundles", [])
        if args.uninstall:
            if PACKAGE_NAME in bundles:
                bundles.remove(PACKAGE_NAME)
        elif PACKAGE_NAME not in bundles:
            bundles.append(PACKAGE_NAME)
        manifest.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("bundles 已更新，尾部:", bundles[-2:])
    except subprocess.CalledProcessError as exc:
        shutil.copy2(backup, manifest)
        print("pnpm 步骤失败（已回滚 package.json）：", exc)
        return 1

    # 自检：合成后的 profile 里应该能看到 artuiux 的 MCP 条目
    try:
        dump = subprocess.run(["dsh", "--profile", args.profile, "--dump-config"],
                              capture_output=True, text=True, timeout=180)
        ok = "art-uiux-mcp" in dump.stdout or "artuiux" in dump.stdout
        skipped = [l for l in dump.stderr.splitlines() if "skipping profile bundle" in l]
        print("dump-config 自检:", "找到 artuiux 条目" if ok else "未找到条目")
        if skipped:
            print("被跳过的 bundle:", skipped)
    except Exception as exc:  # noqa: BLE001
        print("dump-config 自检失败:", exc)

    print("\n需要重启 DSH 才会加载新模块（patchReload=startup）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
