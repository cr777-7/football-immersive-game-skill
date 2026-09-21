#!/usr/bin/env python3
"""Create design documents, not a game engine. Python 3.9+, no dependencies."""
import argparse
from pathlib import Path
import shutil
import sys


def create_project(target, mode):
    target = Path(target).expanduser()
    if mode not in {'open', 'narrative', 'career', 'hybrid'}:
        raise ValueError('Unknown mode')
    if target.exists() or target.is_symlink():
        raise FileExistsError(f'Refusing to overwrite existing path: {target}')
    templates = Path(__file__).resolve().parents[1] / 'assets' / 'templates'
    names = ['brief.md', 'decisions.md', 'playtest.md']
    if mode != 'open':
        names += ['facts.csv', 'assets.json']
    files = {f'design/{name}': templates / name for name in names}
    if mode in {'narrative', 'hybrid'}:
        files['game/story.json'] = templates / 'story.json'
    if mode in {'career', 'hybrid'}:
        files['design/career-model.md'] = templates / 'career-model.md'
    # Read everything before creating the target, so missing templates leave no partial project.
    contents = {name: source.read_bytes() for name, source in files.items()}
    target.mkdir(parents=True, exist_ok=False)
    try:
        for name, content in contents.items():
            dest = target / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
        (target / 'README.md').write_text(
            '# 足球游戏工作目录\n\n'
            f'模式：{mode}\n\n'
            '这是设计文档与数据样例，还不是可运行游戏。\n'
            '先补充 design/brief.md，再由 AI 制作可玩样片。\n'
            '若存在 game/story.json，其中人物与事件均为原创虚构，'
            '仅演示节点结构，请按项目需求替换。\n', encoding='utf-8')
    except Exception:
        shutil.rmtree(target)
        raise
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', type=Path)
    parser.add_argument('--mode', choices=['open', 'narrative', 'career', 'hybrid'], default='open')
    args = parser.parse_args()
    try:
        result = create_project(args.target, args.mode)
    except (OSError, ValueError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    print(f'Created design scaffold: {result.resolve()}')
    print('No game engine has been generated. Continue with the design brief and playable slice.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
