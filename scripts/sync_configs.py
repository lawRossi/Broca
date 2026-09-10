#!/usr/bin/env python3
"""同步/初始化 Broca 配置文件到用户目录（~/.broca）。

由 install.sh 与 install.ps1 共同调用，统一跨平台的配置复制逻辑：
  1. configs.json      — 首次创建（复制源码并改写路径为实际安装路径）；
                          已存在时合并缺失字段（如 execution 分组），保留用户自定义值。
  2. llm_config.json   — 首次创建（同时复制模板）。
  3. agents/           — 递归复制（覆盖更新）。
  4. tool_permission_config.json — 覆盖复制。
  5. skills/           — 镜像同步（删除目标中源码已移除的文件，对应 rsync -a --delete 语义）。

示例（Unix / Windows 通用）:
  python sync_configs.py --project-root /path/to/Broca --broca-home ~/.broca
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path


def log(msg: str) -> None:
    print(f"[sync_configs] {msg}")


def warn(msg: str) -> None:
    print(f"[sync_configs][WARN] {msg}", file=sys.stderr)


def read_json(path: Path):
    """读取 JSON 文件，缺失/损坏返回 None。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def write_json(path: Path, config: dict) -> None:
    """临时文件 + os.replace 原子写入。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)
        f.write("\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# 1. configs.json
# ---------------------------------------------------------------------------
def sync_configs_json(src: Path, dst: Path, db_dir: Path, config_dir: Path, log_dir: Path) -> None:
    """configs.json 同步：首次创建则复制并改写路径；已存在则合并缺失字段。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        warn(f"未找到默认配置: {src}")
        return

    if not dst.exists():
        config = read_json(src)
        if not isinstance(config, dict):
            warn(f"默认配置 {src} 内容非法，跳过创建")
            return
        # 改写路径为实际安装路径（跨平台刷新为字符串值）
        config["database_dir"] = str(db_dir)
        config["llm_config_file"] = str(config_dir / "llm_config.json")
        config["log_file"] = str(log_dir / "agent.log")
        write_json(dst, config)
        log(f"已创建用户配置: {dst}")
        return

    # 已存在：合并缺失字段（如 execution 分组），保留用户已有值
    user_cfg = read_json(dst)
    if not isinstance(user_cfg, dict):
        warn(f"用户配置 {dst} 内容非法，跳过合并")
        return
    src_cfg = read_json(src)
    changed = False
    if isinstance(src_cfg, dict):
        src_exec = src_cfg.get("execution")
        if isinstance(src_exec, dict):
            user_exec = user_cfg.get("execution")
            if not isinstance(user_exec, dict):
                user_exec = {}
            for k, v in src_exec.items():
                if k not in user_exec:
                    user_exec[k] = v
                    changed = True
            if changed:
                user_cfg["execution"] = user_exec
    if changed:
        write_json(dst, user_cfg)
        log(f"用户配置已存在: {dst}，已合并缺失字段（execution 等）")
    else:
        log(f"用户配置已存在: {dst}（无需合并）")


# ---------------------------------------------------------------------------
# 2. llm_config.json
# ---------------------------------------------------------------------------
def sync_llm_config(src: Path, dst_template: Path, dst_config: Path) -> None:
    """llm_config：模板每次覆盖复制；用户配置仅首次创建。"""
    if not src.exists():
        warn(f"未找到 LLM 配置模板: {src}")
        return
    dst_template.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst_template)  # 模板每次都更新
    if not dst_config.exists():
        shutil.copy2(src, dst_config)
        log(f"已创建用户 LLM 配置: {dst_config}")
    else:
        log(f"用户 LLM 配置已存在: {dst_config}（跳过）")


# ---------------------------------------------------------------------------
# 3. agents/  4. tool_permission_config.json  5. skills/
# ---------------------------------------------------------------------------
def copy_tree_overwrite(src: Path, dst: Path, recursive: bool = True) -> None:
    """复制目录/文件覆盖到目标。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        dst.mkdir(parents=True, exist_ok=True)
        if recursive:
            for item in src.iterdir():
                copy_tree_overwrite(item, dst / item.name, recursive=True)
        else:
            for item in src.iterdir():
                if item.is_file():
                    shutil.copy2(item, dst / item.name)
    elif src.is_file():
        shutil.copy2(src, dst)


def sync_mirror(src: Path, dst: Path) -> None:
    """镜像同步目录：把 src 复制到 dst，并删除 dst 中 src 不存在的项（对应 rsync -a --delete）。"""
    if not src.is_dir():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in dst.iterdir():
        if not (src / item.name).exists():
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            sync_mirror(item, target)
        else:
            # 覆盖复制（copy2 保留 mtime/权限），确保内容与源一致
            shutil.copy2(item, target)


def main() -> int:
    parser = argparse.ArgumentParser(description="同步 Broca 配置到用户目录")
    parser.add_argument("--project-root", required=True, help="Broca 项目根目录")
    parser.add_argument("--broca-home", required=True, help="用户配置目录（~/.broca）")
    args = parser.parse_args()

    project_root = Path(args.project_root)
    broca_home = Path(args.broca_home)

    config_dir = broca_home / "configs"
    db_dir = broca_home / "data"
    log_dir = broca_home / "logs"
    skills_dir = broca_home / "skills"

    src_configs = project_root / "configs" / "configs.json"
    dst_configs = config_dir / "configs.json"
    sync_configs_json(src_configs, dst_configs, db_dir, config_dir, log_dir)

    src_llm = project_root / "configs" / "llm_config_template.json"
    sync_llm_config(
        src_llm,
        config_dir / "llm_config_template.json",
        config_dir / "llm_config.json",
    )

    src_agents = project_root / "configs" / "agents"
    dst_agents = config_dir / "agents"
    if src_agents.is_dir():
        if dst_agents.exists():
            shutil.rmtree(dst_agents, ignore_errors=True)
        copy_tree_overwrite(src_agents, dst_agents)
        log(f"Agent 配置已更新: {dst_agents}")
    else:
        warn(f"未找到 Agent 配置目录: {src_agents}")

    src_perm = project_root / "configs" / "tool_permission_config.json"
    dst_perm = config_dir / "tool_permission_config.json"
    if src_perm.exists():
        copy_tree_overwrite(src_perm, dst_perm)
        log(f"已创建工具权限配置: {dst_perm}")
    else:
        warn(f"未找到默认工具权限配置: {src_perm}")

    src_skills = project_root / "skills"
    if src_skills.is_dir():
        sync_mirror(src_skills, skills_dir)
        log(f"Skills 已部署: {skills_dir}")
    else:
        warn(f"未找到 Skills 目录: {src_skills}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
