#!/usr/bin/env python3
"""
btx-web static audit.

Two checks that catch the silent classes of bug we've hit in this repo:

  1. Tailwind color tokens
     Every `bg-X / text-X / border-X / ring-X / accent-X / from-X / to-X`
     class name in any .tsx is cross-referenced against the actual
     `tailwind.config.ts` color keys plus the built-in Tailwind palette.
     Catches the case where a CSS variable exists in globals.css but the
     matching Tailwind token was never declared (so the class doesn't
     resolve and the element renders unstyled). This was the bg-menu
     bug fixed in commit c3795af.

  2. Named imports vs exports
     Every `import { X } from './Y'` (and `import X from './Y'` for
     defaults) is cross-referenced against the actual exports of `./Y`.
     Catches "looks shipped but isn't" gaps where a file references a
     symbol that was deleted, renamed, or never exported.

Exit code: 0 if both audits pass, 1 if any real issue found.

Run from the btx-web/ root:

    python3 scripts/audit.py

Hook into pre-commit (or just run before `npm run dev`).
"""
from __future__ import annotations

import glob
import os
import re
import sys


# -------- audit 1: Tailwind classes vs declared tokens --------

COLOR_PREFIXES = (
    'bg-', 'text-', 'border-', 'ring-', 'accent-', 'decoration-',
    'from-', 'to-', 'via-', 'fill-', 'stroke-', 'placeholder-',
    'caret-', 'outline-',
)

# Tailwind utility values that share a color-class prefix but aren't colors.
# We list them explicitly so the audit doesn't false-positive on them.
NOT_COLOR = {
    # text alignment / font size / leading
    'left', 'right', 'center', 'justify', 'start', 'end',
    'xs', 'sm', 'base', 'lg', 'xl', '2xl', '3xl', '4xl', '5xl', '6xl', '7xl', '8xl', '9xl',
    # border directional shorthands (border-t, border-b, etc.) and widths
    't', 'b', 'l', 'r', 'x', 'y',
    't-0', 't-2', 't-4', 't-8',
    'b-0', 'b-2', 'b-4', 'b-8',
    # border styles
    'collapse', 'separate', 'solid', 'dashed', 'dotted', 'double',
    'none', 'auto', 'inherit',
    # gradient direction utilities (bg-gradient-to-br etc.)
    'gradient-to-t', 'gradient-to-tr', 'gradient-to-r', 'gradient-to-br',
    'gradient-to-b', 'gradient-to-bl', 'gradient-to-l', 'gradient-to-tl',
    # background size / repeat / position values that begin with bg-
    'cover', 'contain', 'repeat', 'no-repeat', 'fixed', 'local', 'scroll',
}

BUILTIN_TAILWIND_COLORS = {
    'black', 'white', 'transparent', 'current', 'inherit',
    'slate', 'gray', 'zinc', 'neutral', 'stone',
    'red', 'orange', 'amber', 'yellow', 'lime', 'green', 'emerald',
    'teal', 'cyan', 'sky', 'blue', 'indigo', 'violet', 'purple',
    'fuchsia', 'pink', 'rose',
}


def parse_tailwind_color_tokens(cfg_path: str) -> set[str]:
    with open(cfg_path) as f:
        cfg = f.read()
    # Find the `colors: { ... }` block and pull keys.
    tokens: set[str] = set()
    in_colors = False
    depth = 0
    for line in cfg.splitlines():
        s = line.strip()
        if not in_colors and 'colors:' in s and '{' in s:
            in_colors = True
            depth = 1
            continue
        if in_colors:
            depth += s.count('{') - s.count('}')
            if depth <= 0:
                in_colors = False
                continue
            m = re.match(r"['\"]?([A-Za-z][\w-]*)['\"]?\s*:\s*'#", s)
            if m:
                tokens.add(m.group(1))
    return tokens


def audit_tailwind_classes(root: str, tokens: set[str]) -> list[tuple[str, str, str]]:
    issues: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for fp in sorted(glob.glob(f"{root}/**/*.tsx", recursive=True)):
        with open(fp) as f:
            src = f.read()
        # Pull all className="..." strings (single-string form).
        for cls_str in re.findall(r'className="([^"]+)"', src):
            for tok in cls_str.split():
                base = tok.split(':')[-1].lstrip('!').rstrip('!').split('/')[0]
                if '[' in base:  # arbitrary-value class like text-[10px]
                    continue
                for pref in COLOR_PREFIXES:
                    if not base.startswith(pref):
                        continue
                    color = base[len(pref):]
                    if color in NOT_COLOR:
                        break
                    if color in tokens:
                        break
                    if color in BUILTIN_TAILWIND_COLORS:
                        break
                    if color.replace('-', '').isdigit():
                        break
                    key = (fp, base)
                    if key in seen:
                        break
                    seen.add(key)
                    issues.append((fp, base, color))
                    break
    return issues


# -------- audit 2: named imports vs exports --------

def scan_exports(path: str) -> set[str]:
    exports: set[str] = set()
    try:
        with open(path) as f:
            src = f.read()
    except OSError:
        return exports
    for m in re.finditer(
        r'export\s+(?:async\s+)?(?:function|const|class|interface|type|enum)\s+([A-Za-z_$][\w$]*)',
        src,
    ):
        exports.add(m.group(1))
    for m in re.finditer(r'export\s*\{([^}]+)\}', src):
        for piece in m.group(1).split(','):
            piece = piece.strip()
            if not piece:
                continue
            name = piece.split(' as ')[-1].strip()
            exports.add(name)
    if re.search(r'export\s+default\s+', src):
        exports.add('default')
    return exports


def build_export_index(root: str) -> dict[str, set[str]]:
    idx: dict[str, set[str]] = {}
    files = sorted(
        glob.glob(f"{root}/**/*.tsx", recursive=True)
        + glob.glob(f"{root}/**/*.ts", recursive=True)
    )
    for fp in files:
        idx[fp] = scan_exports(fp)
    return idx


def resolve_import(import_path: str, from_file: str, idx: dict[str, set[str]]) -> str | None:
    if import_path.startswith('@/'):
        base = 'src/' + import_path[2:]
    elif import_path.startswith('.'):
        base = os.path.normpath(os.path.join(os.path.dirname(from_file), import_path))
    else:
        return None
    for cand in (base + '.tsx', base + '.ts', base + '/index.tsx', base + '/index.ts'):
        if cand in idx:
            return cand
    return None


def audit_imports(root: str, idx: dict[str, set[str]]) -> list[tuple[str, str, str, str, list[str]]]:
    issues: list[tuple[str, str, str, str, list[str]]] = []
    for fp in idx:
        with open(fp) as f:
            src = f.read()
        # `import { ... } from '...'` and `import X, { ... } from '...'`
        for m in re.finditer(
            r"import\s+(?:[^,]*?,\s*)?\{([^}]+)\}\s+from\s+['\"]([^'\"]+)['\"]",
            src,
        ):
            names_blob = m.group(1)
            path = m.group(2)
            target = resolve_import(path, fp, idx)
            if target is None:
                continue
            target_exports = idx.get(target, set())
            for raw in names_blob.split(','):
                n = raw.strip()
                if not n:
                    continue
                if n.startswith('type '):
                    n = n[5:].strip()
                n = n.split(' as ')[0].strip()
                if not n or n in target_exports:
                    continue
                issues.append((fp, n, path, target, sorted(target_exports)))
        # `import NAME from '...'`
        for m in re.finditer(
            r"import\s+([A-Za-z_$][\w$]*)\s+from\s+['\"]([^'\"]+)['\"]",
            src,
        ):
            name = m.group(1)
            path = m.group(2)
            target = resolve_import(path, fp, idx)
            if target is None:
                continue
            if 'default' not in idx.get(target, set()):
                issues.append((fp, '(default)', path, target, sorted(idx.get(target, set()))))
    return issues


# -------- main --------

def main() -> int:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg_path = os.path.join(repo_root, 'tailwind.config.ts')
    src_root = os.path.join(repo_root, 'src')
    os.chdir(repo_root)

    fail = 0

    tokens = parse_tailwind_color_tokens('tailwind.config.ts')
    print(f"== audit 1/2: Tailwind color classes ({len(tokens)} declared tokens) ==")
    tw_issues = audit_tailwind_classes('src', tokens)
    if not tw_issues:
        print("  OK")
    else:
        fail = 1
        for fp, base, color in tw_issues:
            print(f"  FAIL  {fp}  uses '{base}' but no '{color}' color token")

    print()
    idx = build_export_index('src')
    print(f"== audit 2/2: named imports vs exports across {len(idx)} files ==")
    imp_issues = audit_imports('src', idx)
    if not imp_issues:
        print("  OK")
    else:
        fail = 1
        for fp, name, path, target, exports in imp_issues:
            print(f"  FAIL  {fp}")
            print(f"        imports {name} from '{path}' (resolved {target})")
            print(f"        actual exports: {', '.join(exports) or '(none)'}")

    print()
    print("== summary: pass ==" if fail == 0 else "== summary: FAIL ==")
    return fail


if __name__ == '__main__':
    sys.exit(main())
