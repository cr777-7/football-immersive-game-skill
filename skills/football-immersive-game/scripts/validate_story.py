#!/usr/bin/env python3
"""Validate the bundled minimal story graph protocol. Not a runtime or fact checker."""
import argparse
import json
import math
from pathlib import Path
import sys


def valid_id(value):
    return isinstance(value, str) and bool(value.strip())


def valid_effect(value):
    # JavaScript consumers must be able to preserve integer effects exactly.
    if type(value) is int:
        return abs(value) <= 2**53 - 1
    return type(value) is float and math.isfinite(value)


def validate(data, project_root=None):
    errors, warnings = [], []
    if not isinstance(data, dict):
        return ['Story must be a JSON object'], warnings
    if type(data.get('schemaVersion')) is not int or data.get('schemaVersion') != 1:
        errors.append('schemaVersion must be 1')
    nodes = data.get('nodes')
    if not isinstance(nodes, list) or not nodes:
        return errors + ['nodes must be a non-empty array'], warnings
    assets = data.get('assets', [])
    if not isinstance(assets, list):
        errors.append('assets must be an array')
        assets = []
    asset_ids = set()
    try:
        root = Path(project_root).resolve() if project_root is not None else None
    except (OSError, RuntimeError, ValueError) as exc:
        return errors + [f'Cannot resolve project root: {exc}'], warnings
    if root is not None and not root.is_dir():
        return errors + [f'Project root is not a directory: {root}'], warnings
    for index, asset in enumerate(assets):
        label = f'assets[{index}]'
        if not isinstance(asset, dict):
            errors.append(f'{label}: must be an object')
            continue
        aid = asset.get('id')
        if not valid_id(aid):
            errors.append(f'{label}: missing/invalid id')
        elif aid in asset_ids:
            errors.append(f'{label}: duplicate asset id {aid}')
        else:
            asset_ids.add(aid)
        path = asset.get('path')
        if not isinstance(path, str) or not path.strip():
            errors.append(f'{label}: path must be a non-empty relative file path')
            continue
        if '\x00' in path or ':' in path or '\\' in path or Path(path).is_absolute() or '..' in Path(path).parts:
            errors.append(f'{label}: unsafe or non-local path {path!r}')
            continue
        if root is not None:
            try:
                resolved = (root / path).resolve()
                exists = resolved.is_file()
            except (OSError, RuntimeError, ValueError) as exc:
                errors.append(f'{label}: cannot resolve asset path {path!r}: {exc}')
                continue
            try:
                resolved.relative_to(root)
            except ValueError:
                errors.append(f'{label}: path escapes project root')
                continue
            if not exists:
                errors.append(f'{label}: missing asset file {path}')
    if assets and root is None:
        warnings.append('No project root supplied; asset file existence was not checked')

    by_id, graph = {}, {}
    for index, node in enumerate(nodes):
        if not isinstance(node, dict) or not valid_id(node.get('id')):
            errors.append(f'nodes[{index}]: must be an object with a non-empty id')
            continue
        nid = node['id']
        if nid in by_id:
            errors.append(f'Duplicate node id: {nid}')
            continue
        by_id[nid] = node
        graph[nid] = []
    for nid, node in by_id.items():
        kind = node.get('type')
        if not isinstance(node.get('text'), str) or not node['text'].strip():
            errors.append(f'{nid}: text must be non-empty')
        refs = node.get('assetIds', [])
        if not isinstance(refs, list):
            errors.append(f'{nid}: assetIds must be an array')
        else:
            for aid in refs:
                if not valid_id(aid) or aid not in asset_ids:
                    errors.append(f'{nid}: unknown asset id {aid!r}')
        if kind == 'scene':
            graph[nid].append(node.get('next'))
            if 'options' in node:
                errors.append(f'{nid}: scene cannot have options')
        elif kind == 'choice':
            if 'next' in node:
                errors.append(f'{nid}: choice uses options, not next')
            options = node.get('options')
            if not isinstance(options, list) or len(options) < 2:
                errors.append(f'{nid}: choice needs at least two options')
                continue
            seen = set()
            for i, opt in enumerate(options):
                label = f'{nid}.options[{i}]'
                if not isinstance(opt, dict):
                    errors.append(f'{label}: must be an object')
                    continue
                oid = opt.get('id')
                if not valid_id(oid) or oid in seen:
                    errors.append(f'{label}: invalid or duplicate option id')
                else:
                    seen.add(oid)
                if not valid_id(opt.get('label')):
                    errors.append(f'{label}: label must be non-empty')
                graph[nid].append(opt.get('next'))
                effects = opt.get('effects', {})
                if not isinstance(effects, dict) or any(
                    not valid_id(k) or not valid_effect(v)
                    for k, v in effects.items()
                ):
                    errors.append(f'{label}: effects must map state keys to finite numbers (integers within JavaScript safe range)')
        elif kind == 'ending':
            if 'next' in node or 'options' in node:
                errors.append(f'{nid}: ending cannot have outgoing transitions')
        else:
            errors.append(f'{nid}: unsupported node type {kind!r}')
    for nid, targets in graph.items():
        for target in targets:
            if not valid_id(target) or target not in by_id:
                errors.append(f'{nid}: missing target {target!r}')
    start = data.get('start')
    if not valid_id(start) or start not in by_id:
        errors.append('start must reference an existing node')
    if errors:
        return errors, warnings
    reachable, todo = set(), [start]
    while todo:
        nid = todo.pop()
        if nid not in reachable:
            reachable.add(nid)
            todo.extend(graph[nid])
    for nid in sorted(set(by_id) - reachable):
        errors.append(f'Unreachable node: {nid}')
    endings = {nid for nid in reachable if by_id[nid]['type'] == 'ending'}
    if not endings:
        errors.append('No reachable ending')
    reverse = {nid: [] for nid in by_id}
    for nid, targets in graph.items():
        for target in targets:
            reverse[target].append(nid)
    can_finish, todo = set(), list(endings)
    while todo:
        nid = todo.pop()
        if nid not in can_finish:
            can_finish.add(nid)
            todo.extend(reverse[nid])
    for nid in sorted(reachable - can_finish):
        errors.append(f'No path to an ending from: {nid}')
    # Kahn's algorithm avoids recursion depth issues on long stories.
    indegree = {nid: 0 for nid in reachable}
    for nid in reachable:
        for target in graph[nid]:
            indegree[target] += 1
    todo = [nid for nid, degree in indegree.items() if degree == 0]
    removed = 0
    while todo:
        nid = todo.pop()
        removed += 1
        for target in graph[nid]:
            indegree[target] -= 1
            if indegree[target] == 0:
                todo.append(target)
    if removed != len(reachable):
        warnings.append('Reachable cycle detected; verify exit rules and runtime state conditions')
    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('story', type=Path)
    parser.add_argument('--project-root', type=Path)
    args = parser.parse_args()
    try:
        with args.story.open(encoding='utf-8') as stream:
            data = json.load(stream)
        errors, warnings = validate(data, args.project_root)
    except (OSError, ValueError, RecursionError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    for warning in warnings:
        print(f'WARNING: {warning}')
    for error in errors:
        print(f'ERROR: {error}', file=sys.stderr)
    if errors:
        return 1
    print('PASS: story structure is valid. Runtime behavior and facts still need review.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
