#!/usr/bin/env python3
"""
P3_CUAS Code Explorer - bygger en interaktiv HTML-side ud fra koden i repoet.

Brug:
    python build_explorer.py                 # henter/opdaterer repoet fra GitHub og bygger siden
    python build_explorer.py --repo STI      # bruger en lokal checkout i stedet
    python build_explorer.py --check         # fejler (exit 1) hvis noget mangler en beskrivelse

Scriptet læser selv strukturen (filer, klasser, metoder, parametre, return-værdier,
hvem der kalder hvem, Flask-routes, knapper i HTML og config-konstanter).
Forklaringerne skrives i descriptions.json. Nye funktioner får automatisk en tom
skabelon i descriptions.json, så man bare skal udfylde teksten og køre scriptet igen.

Kun standardbiblioteket bruges (Python 3.9+).
"""
import argparse
import ast
import builtins
import datetime
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_REMOTE = "https://github.com/twoods25/P3_CUAS.git"
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", "recordings",
             "TobiasTest", ".idea", ".vscode", ".repo_cache", "code_explorer"}
TEXT_NAMES = {"Dockerfile", ".gitignore", ".dockerignore", "Makefile", "LICENSE"}
TEXT_EXT = {".py", ".html", ".htm", ".js", ".css", ".md", ".txt", ".yml", ".yaml", ".json",
            ".toml", ".cfg", ".ini", ".sh", ".xml", ".launch", ".msg", ".srv", ".cpp", ".h",
            ".hpp", ".c", ".cmake"}
SENSITIVE = re.compile(r"(IP|HOST|USER|PASS|PWD|KEY|TOKEN|SECRET)", re.I)
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
BUILTIN_NAMES = set(dir(builtins))
LIFECYCLE = {"__init__", "start", "stop", "run", "join"}
RESERVED_HASH = {"settings", "sidebar", "customize", "upgrade", "downloads"}
DOC_KINDS = {"class", "method", "function", "route", "entry", "jsfunc"}


def git(args, cwd):
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return ""


def find_repo(arg_repo, remote):
    """Lokal sti (--repo) eller klon/opdater gruppens repo i .repo_cache."""
    if arg_repo:
        return Path(arg_repo).resolve()
    cache = HERE / ".repo_cache"
    if (cache / ".git").exists():
        print("Opdaterer repo i", cache)
        git(["fetch", "--depth", "1", "origin"], cache)
        git(["reset", "--hard", "origin/HEAD"], cache)
    else:
        print("Kloner", remote)
        subprocess.run(["git", "clone", "--depth", "1", remote, str(cache)], check=True)
    return cache


def slug(key, used):
    s = re.sub(r"[^A-Za-z0-9]+", "-", key).strip("-").lower() or "repo"
    if s in RESERVED_HASH or s.startswith("comment"):
        s = "x-" + s
    base, n = s, 2
    while s in used:
        s = f"{base}-{n}"
        n += 1
    used.add(s)
    return s


def own_nodes(node):
    """Alle AST-noder i en funktions krop, men ikke inde i indlejrede def/class."""
    stack = list(node.body)
    while stack:
        n = stack.pop(0)
        yield n
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue  # selve def'en gives videre (så indlejrede kan findes), men ikke kroppen
        stack.extend(ast.iter_child_nodes(n))


class Ctx:
    def __init__(self, rel, cls=None):
        self.rel, self.cls, self.local = rel, cls, {}


class Builder:
    def __init__(self, root, desc):
        self.root, self.desc = root, desc
        self.sym = {}
        self.edges = []          # (from, to, kind, label)
        self.funcs = {}          # key -> (astnode, cls_key, rel)
        self.imported = defaultdict(dict)   # rel -> name -> key | ("module", name)
        self.module_funcs = defaultdict(dict)
        self.classes = {}        # key -> {"methods": {name: key}, "init": [params]}
        self.param_types = defaultdict(dict)
        self.attr_types = defaultdict(dict)
        self.secrets = set()
        self.routes = {}         # path -> key
        self.pending_http = []   # (from, path, label)
        self.texts = {}
        cfg = desc.get("config_files") or ["credentials.py", "config.py", "settings.py", "params.py"]
        self.config_names = set(cfg)

    # ---------- generelt ----------
    def add(self, key, kind, name, parent, **kw):
        s = {"key": key, "kind": kind, "name": name, "parent": parent, "children": []}
        s.update(kw)
        self.sym[key] = s
        if parent is not None:
            self.sym[parent]["children"].append(key)
        return s

    def ensure_folder(self, rel_dir):
        if rel_dir in self.sym:
            return rel_dir
        if rel_dir == "":
            self.add("", "folder", self.desc.get("repo_name", self.root.name), None)
            return ""
        parent = rel_dir.rsplit("/", 1)[0] if "/" in rel_dir else ""
        self.ensure_folder(parent)
        self.add(rel_dir, "folder", rel_dir.split("/")[-1], parent)
        return rel_dir

    def redact(self, text):
        for s in sorted(self.secrets, key=len, reverse=True):
            text = text.replace(s, "•••")
        return IPV4.sub("•••", text)

    # ---------- filer ----------
    def scan(self):
        self.ensure_folder("")
        files = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and d not in self.desc.get("skip", []))
            for f in sorted(filenames):
                p = Path(dirpath) / f
                rel = p.relative_to(self.root).as_posix()
                files.append(rel)
        # config-filer først, så deres hemmeligheder er kendt før redigering
        files.sort(key=lambda r: (Path(r).name not in self.config_names, r.count("/") == 0, r))
        for rel in files:
            p = self.root / rel
            parent = self.ensure_folder(rel.rsplit("/", 1)[0] if "/" in rel else "")
            is_text = p.suffix.lower() in TEXT_EXT or p.name in TEXT_NAMES
            size = p.stat().st_size
            text = None
            if is_text and size < 400_000:
                text = p.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
                self.texts[rel] = text
            self.add(rel, "file", p.name, parent, file=rel, size=size, text=is_text,
                     ext=p.suffix.lower() or p.name)
        for rel in files:
            if rel.endswith(".py") and rel in self.texts:
                self.register_python(rel)
        self.infer_types()
        for rel in files:
            if rel.endswith(".py") and rel in self.texts:
                self.collect_python_edges(rel)
        for rel in files:
            if rel.endswith((".html", ".htm")) and rel in self.texts:
                self.parse_html(rel)
        for frm, path, label in self.pending_http:
            to = self.routes.get(path)
            if to:
                self.edges.append((frm, to, "http", label))
        # kildekode til hver fil (efter at alle hemmeligheder er fundet)
        for rel, text in self.texts.items():
            self.sym[rel]["source"] = self.redact_config(rel, text)
            self.sym[rel]["line"] = 1

    def redact_config(self, rel, text):
        if Path(rel).name in self.config_names:
            text = re.sub(r"(?m)^(\s*(\w+)\s*=\s*)([^#\n]*?)(\s*(#.*)?)$",
                          lambda m: m.group(1) + ("•••" if SENSITIVE.search(m.group(2)) else m.group(3)) + m.group(4),
                          text)
        return self.redact(text)

    # ---------- python: registrering ----------
    def register_python(self, rel):
        text = self.texts[rel]
        try:
            tree = ast.parse(text)
        except SyntaxError as e:
            self.sym[rel]["error"] = f"SyntaxError: {e}"
            return
        lines = text.split("\n")
        self.sym[rel]["module_doc"] = ast.get_docstring(tree)
        is_config = Path(rel).name in self.config_names
        if is_config:
            self.sym[rel]["config"] = True
        here_dir = rel.rsplit("/", 1)[0] if "/" in rel else ""

        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module:
                cand = [f"{here_dir}/{node.module.replace('.', '/')}.py".lstrip("/"),
                        f"{node.module.replace('.', '/')}.py"]
                target = next((c for c in cand if c in self.sym), None)
                for a in node.names:
                    nm = a.asname or a.name
                    if target:
                        self.imported[rel][nm] = f"{target}::{a.name}"
                    else:
                        self.imported[rel][nm] = ("module", f"{node.module}.{a.name}")
                if target:
                    self.edges.append((rel, target, "import", ", ".join(a.name for a in node.names)))
            elif isinstance(node, ast.Import):
                for a in node.names:
                    self.imported[rel][a.asname or a.name.split(".")[0]] = ("module", a.name)
            elif isinstance(node, ast.ClassDef):
                self.register_class(rel, node, lines)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                key = self.register_func(rel, node, rel, node.name, None, lines)
                self.module_funcs[rel][node.name] = key
            elif isinstance(node, ast.If) and "__name__" in ast.unparse(node.test):
                key = f"{rel}::__main__"
                self.add(key, "entry", 'if __name__ == "__main__"', rel, file=rel,
                         line=node.lineno, end=node.end_lineno,
                         source=self.redact("\n".join(lines[node.lineno - 1:node.end_lineno])),
                         params=[], returns=[], signature='if __name__ == "__main__":')
                self.funcs[key] = (node, None, rel)
            elif is_config and isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                raw = ast.unparse(node.value)
                sensitive = bool(SENSITIVE.search(name))
                if sensitive and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str) \
                        and len(node.value.value) >= 3:
                    self.secrets.add(node.value.value)
                line_txt = lines[node.lineno - 1]
                comment = line_txt.split("#", 1)[1].strip() if "#" in line_txt else ""
                self.add(f"{rel}::{name}", "config", name, rel, file=rel, line=node.lineno,
                         end=node.end_lineno, value="•••" if sensitive else raw,
                         sensitive=sensitive, comment=comment)

    def leading_comments(self, node, lines):
        start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
        out, i = [], start - 2
        while i >= 0 and lines[i].strip().startswith("#"):
            out.insert(0, lines[i].strip().lstrip("#").strip())
            i -= 1
        return out, i + 2

    def register_class(self, rel, node, lines):
        key = f"{rel}::{node.name}"
        comments, start = self.leading_comments(node, lines)
        bases = [ast.unparse(b) for b in node.bases]
        thread = any(b.split(".")[-1] == "Thread" for b in bases)
        self.add(key, "class", node.name, rel, file=rel, line=start, def_line=node.lineno,
                 end=node.end_lineno, bases=bases, thread=thread, comments=comments,
                 docstring=ast.get_docstring(node),
                 source=self.redact("\n".join(lines[start - 1:node.end_lineno])))
        info = {"methods": {}, "init": []}
        self.classes[key] = info
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                mkey = self.register_func(rel, item, key, f"{node.name}.{item.name}", key, lines)
                info["methods"][item.name] = mkey
                if item.name == "__init__":
                    info["init"] = [p["name"] for p in self.sym[mkey]["params"]]

    def register_func(self, rel, node, parent, qual, cls_key, lines):
        key = f"{rel}::{qual}"
        a = node.args
        pos = a.posonlyargs + a.args
        defaults = [None] * (len(pos) - len(a.defaults)) + list(a.defaults)
        params = []
        for i, (arg, d) in enumerate(zip(pos, defaults)):
            if i == 0 and cls_key and parent == cls_key and arg.arg in ("self", "cls"):
                continue
            params.append({"name": arg.arg, "default": ast.unparse(d) if d is not None else None,
                           "ann": ast.unparse(arg.annotation) if arg.annotation else None})
        if a.vararg:
            params.append({"name": "*" + a.vararg.arg, "default": None, "ann": None})
        for arg, d in zip(a.kwonlyargs, a.kw_defaults):
            params.append({"name": arg.arg, "default": ast.unparse(d) if d is not None else None,
                           "ann": ast.unparse(arg.annotation) if arg.annotation else None})
        if a.kwarg:
            params.append({"name": "**" + a.kwarg.arg, "default": None, "ann": None})

        route = None
        for d in node.decorator_list:
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "route" and d.args:
                path = ast.literal_eval(d.args[0]) if isinstance(d.args[0], ast.Constant) else ast.unparse(d.args[0])
                methods = ["GET"]
                for kw in d.keywords:
                    if kw.arg == "methods":
                        try:
                            methods = list(ast.literal_eval(kw.value))
                        except Exception:
                            methods = [ast.unparse(kw.value)]
                route = {"path": path, "methods": methods}

        returns = []
        for n in own_nodes(node):
            if isinstance(n, ast.Return):
                r = ast.unparse(n.value) if n.value is not None else "None"
                if r not in returns:
                    returns.append(r)
        comments, start = self.leading_comments(node, lines)
        def_line = lines[node.lineno - 1]
        inline = def_line.split("#", 1)[1].strip() if "#" in def_line else ""
        if route:
            kind = "route"
        elif cls_key and parent == cls_key:
            kind = "method"
        else:
            kind = "function"
        sig_params = ", ".join(p["name"] + (f"={p['default']}" if p["default"] else "") for p in params)
        self.add(key, kind, node.name, parent, file=rel, line=start, def_line=node.lineno,
                 end=node.end_lineno, params=params, returns=returns, comments=comments,
                 inline_comment=inline, docstring=ast.get_docstring(node), route=route,
                 decorators=[ast.unparse(d) for d in node.decorator_list],
                 private=node.name.startswith("_") and not node.name.startswith("__"),
                 signature=f"{'async ' if isinstance(node, ast.AsyncFunctionDef) else ''}def {node.name}({sig_params})",
                 source=self.redact("\n".join(lines[start - 1:node.end_lineno])))
        if route:
            self.routes[route["path"]] = key
        self.funcs[key] = (node, cls_key, rel)
        for n in own_nodes(node):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n is not node:
                self.register_func(rel, n, key, f"{qual}.{n.name}", cls_key, lines)
        return key

    # ---------- python: typer (hvilket objekt ligger i self.feed osv.) ----------
    def expr_type(self, e, ctx):
        if isinstance(e, ast.Name):
            if e.id == "self" and ctx.cls:
                return ("inst", ctx.cls)
            if e.id in ctx.local:
                return ctx.local[e.id]
            imp = self.imported[ctx.rel].get(e.id)
            if isinstance(imp, str) and imp in self.sym:
                k = self.sym[imp]["kind"]
                return ("classref", imp) if k == "class" else ("func", imp) if k == "function" else None
            if e.id in self.module_funcs[ctx.rel]:
                return ("func", self.module_funcs[ctx.rel][e.id])
            local_cls = f"{ctx.rel}::{e.id}"
            if local_cls in self.classes:
                return ("classref", local_cls)
            return None
        if isinstance(e, ast.Attribute):
            base = self.expr_type(e.value, ctx)
            if base and base[0] == "inst":
                cls = base[1]
                if e.attr in self.classes.get(cls, {}).get("methods", {}):
                    return ("bound", self.classes[cls]["methods"][e.attr])
                return self.attr_types[cls].get(e.attr) or self.hint(e.attr)
            if isinstance(e.value, ast.Name) and e.value.id == "self":
                return self.hint(e.attr)
            return None
        if isinstance(e, ast.Call):
            f = self.expr_type(e.func, ctx)
            if f and f[0] == "classref":
                return ("inst", f[1])
        return None

    def hint(self, attr):
        h = self.desc.get("type_hints", {}).get(attr)
        return ("inst", h) if h in self.classes else None

    def infer_types(self):
        for _ in range(4):
            for key, (node, cls, rel) in self.funcs.items():
                ctx = Ctx(rel, cls)
                if cls and self.sym[key]["name"] == "__init__":
                    for p in self.sym[key]["params"]:
                        t = self.param_types[cls].get(p["name"])
                        if t:
                            ctx.local[p["name"]] = t
                body = node.body if isinstance(node, ast.If) else node.body
                for n in own_nodes(ast.Module(body=body, type_ignores=[])):
                    if isinstance(n, ast.Assign):
                        for tgt in n.targets:
                            self.assign(tgt, n.value, ctx)
                    elif isinstance(n, ast.Call):
                        f = self.expr_type(n.func, ctx)
                        if f and f[0] == "classref":
                            init = self.classes[f[1]]["init"]
                            for i, arg in enumerate(n.args):
                                t = self.expr_type(arg, ctx)
                                if t and i < len(init):
                                    self.param_types[f[1]][init[i]] = t
                            for kw in n.keywords:
                                t = self.expr_type(kw.value, ctx)
                                if t and kw.arg:
                                    self.param_types[f[1]][kw.arg] = t

    def assign(self, tgt, val, ctx):
        if isinstance(tgt, ast.Tuple) and isinstance(val, ast.Tuple) and len(tgt.elts) == len(val.elts):
            for t, v in zip(tgt.elts, val.elts):
                self.assign(t, v, ctx)
            return
        t = self.expr_type(val, ctx)
        if not t:
            return
        if isinstance(tgt, ast.Name):
            ctx.local[tgt.id] = t
        elif isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name) and tgt.value.id == "self" and ctx.cls:
            self.attr_types[ctx.cls][tgt.attr] = t

    # ---------- python: kanter ----------
    def collect_python_edges(self, rel):
        config_keys = {nm: k for nm, k in self.imported[rel].items()
                       if isinstance(k, str) and k in self.sym and self.sym[k]["kind"] == "config"}
        html_files = {Path(k).name: k for k, s in self.sym.items()
                      if s["kind"] == "file" and k.endswith((".html", ".htm"))}
        for key, (node, cls, frel) in self.funcs.items():
            if frel != rel:
                continue
            ctx = Ctx(rel, cls)
            if cls and self.sym[key]["name"] == "__init__":
                for p in self.sym[key]["params"]:
                    t = self.param_types[cls].get(p["name"])
                    if t:
                        ctx.local[p["name"]] = t
            externals, cfg_used = [], []
            body = node.body
            extra = []
            if not isinstance(node, ast.If):
                extra = list(node.args.defaults) + [d for d in node.args.kw_defaults if d is not None]
            for n in list(own_nodes(ast.Module(body=body, type_ignores=[]))) + \
                    [x for d in extra for x in ast.walk(d)]:
                if isinstance(n, ast.Assign):
                    for tgt in n.targets:
                        self.assign(tgt, n.value, ctx)
                if isinstance(n, ast.Name) and n.id in config_keys and config_keys[n.id] not in cfg_used:
                    cfg_used.append(config_keys[n.id])
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in html_files:
                    self.edges.append((key, html_files[n.value], "serves", "sender siden"))
                if not isinstance(n, ast.Call):
                    continue
                f = self.expr_type(n.func, ctx)
                if f and f[0] == "classref":
                    self.edges.append((key, f[1], "creates", f"{self.sym[f[1]]['name']}(...)"))
                elif f and f[0] in ("bound", "func"):
                    self.edges.append((key, f[1], "call", f"{self.sym[f[1]]['name']}()"))
                else:
                    name = ast.unparse(n.func)
                    if name == "self.start" and cls and self.sym[cls].get("thread"):
                        run = self.classes[cls]["methods"].get("run")
                        if run:
                            self.edges.append((key, run, "thread", "start() → run() i ny tråd"))
                        continue
                    root = name.split(".")[0].split("(")[0]
                    if name.startswith("super(") or (root in BUILTIN_NAMES and "." not in name):
                        continue
                    if len(name) > 60:
                        name = name[:57] + "..."
                    if name not in externals:
                        externals.append(name)
            for k in cfg_used:
                self.edges.append((key, k, "config", self.sym[k]["name"]))
            self.sym[key]["externals"] = externals[:40]

    # ---------- html ----------
    def parse_html(self, rel):
        text = self.texts[rel]
        buttons_html = {m.group(1): re.sub(r"<[^>]+>", "", m.group(2)).strip()
                        for m in re.finditer(r'<button[^>]*id="([^"]+)"[^>]*>(.*?)</button>', text, re.S | re.I)}
        funcs = {}
        spans = []
        for sm in re.finditer(r"<script[^>]*>(.*?)</script>", text, re.S | re.I):
            script, off = sm.group(1), sm.start(1)
            for fm in re.finditer(r"(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)\s*\{", script):
                i, depth = fm.end() - 1, 0
                while i < len(script):
                    depth += {"{": 1, "}": -1}.get(script[i], 0)
                    if depth == 0:
                        break
                    i += 1
                a, b = off + fm.start(), off + i + 1
                spans.append((a, b))
                funcs[fm.group(1)] = (a, b, [p.strip() for p in fm.group(2).split(",") if p.strip()])
        jsnames = set(funcs)
        lineno = lambda pos: text.count("\n", 0, pos) + 1

        def scan_calls(src, frm, label_prefix=""):
            for m in re.finditer(r"""fetch\(\s*["'](/[^"']*)["']""", src):
                self.pending_http.append((frm, m.group(1), label_prefix + "fetch " + m.group(1)))
            for m in re.finditer(r"""\b(\w+)\(\s*["'](/[^"']*)["']""", src):
                if m.group(1) in jsnames:
                    self.pending_http.append((frm, m.group(2), label_prefix + f"{m.group(1)}('{m.group(2)}')"))

        for name, (a, b, params) in funcs.items():
            key = f"{rel}::{name}"
            src = text[a:b]
            first = src.split("\n", 1)[0]
            self.add(key, "jsfunc", name, rel, file=rel, line=lineno(a), end=lineno(b),
                     params=[{"name": p, "default": None, "ann": None} for p in params],
                     returns=[], signature=first.rstrip("{ ").strip(), source=self.redact(src),
                     externals=sorted(set(re.findall(r"\b(fetch|document\.getElementById|JSON\.stringify)\b", src))))
            scan_calls(src, key)
            for other in jsnames - {name}:
                if re.search(rf"\b{other}\s*\(", src):
                    self.edges.append((key, f"{rel}::{other}", "call", f"{other}()"))
        # kode uden for funktioner: knapper og opstart
        top = text
        for a, b in sorted(spans, reverse=True):
            top = top[:a] + top[b:]
        buttons = []
        for m in re.finditer(r"""getElementById\(\s*["'](\w+)["']\s*\)\.onclick\s*=\s*[^;\n]*?(\w+)\(\s*["'](/[^"']*)["']""", top):
            bid, handler, path = m.groups()
            label = buttons_html.get(bid, bid)
            buttons.append({"id": bid, "label": label, "handler": handler, "route": path})
            self.pending_http.append((rel, path, f"knap “{label}”"))
        for m in re.finditer(r"""^(?!.*onclick).*fetch\(\s*["'](/[^"']*)["']""", top, re.M):
            self.pending_http.append((rel, m.group(1), "ved sideindlæsning"))
        for name in jsnames:
            if re.search(rf"\b{name}\s*\(", top):
                self.edges.append((rel, f"{rel}::{name}", "call", f"{name}()"))
        self.sym[rel]["buttons"] = buttons

    # ---------- eksterne noder fra descriptions.json ----------
    def add_externals(self):
        for ext in self.desc.get("external_nodes", []):
            key = "ext:" + ext["id"]
            self.add(key, "external", ext.get("label", ext["id"]), None, sub=ext.get("sub", ""),
                     doc={"summary": ext.get("summary", "")})
            for l in ext.get("links", []):
                frm = key if l.get("from") == "self" else l.get("from")
                to = key if l.get("to") == "self" else l.get("to")
                if frm in self.sym and to in self.sym:
                    self.edges.append((frm, to, l.get("kind", "io"), l.get("label", "")))
                else:
                    print(f"  ! ekstern forbindelse peger på ukendt nøgle: {l}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", help="lokal sti til repoet (ellers hentes det fra GitHub)")
    ap.add_argument("--remote", default=DEFAULT_REMOTE)
    ap.add_argument("--out", default=str(HERE / "P3_CUAS_explorer.html"))
    ap.add_argument("--desc", default=str(HERE / "descriptions.json"))
    ap.add_argument("--check", action="store_true", help="exit 1 hvis noget mangler beskrivelse")
    args = ap.parse_args()

    desc_path = Path(args.desc)
    desc = json.loads(desc_path.read_text(encoding="utf-8")) if desc_path.exists() else {}
    desc.setdefault("symbols", {})
    repo = find_repo(args.repo, args.remote)
    b = Builder(repo, desc)
    b.scan()
    b.add_externals()

    commit = git(["rev-parse", "HEAD"], repo)
    commit_date = git(["log", "-1", "--format=%cI"], repo)
    remote = git(["config", "--get", "remote.origin.url"], repo) or args.remote
    m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", remote)
    web = f"https://github.com/{m.group(1)}" if m else ""

    # beskrivelser
    docs = desc["symbols"]
    missing, stale = [], [k for k in docs if k not in b.sym and not k.startswith("_")]
    for key, s in b.sym.items():
        d = docs.get(key)
        needs = s["kind"] in DOC_KINDS or (s["kind"] == "file" and s["ext"] in (".py", ".html")) \
            or s["kind"] == "folder" and key == ""
        if d:
            s["doc"] = d
        if needs and not (d and d.get("summary", "").strip()):
            missing.append(key)
            if key not in docs:
                docs[key] = {"summary": ""}
                if s.get("params"):
                    docs[key]["params"] = {p["name"]: "" for p in s["params"]}
                if s["kind"] in ("method", "function", "route", "jsfunc"):
                    docs[key]["returns"] = ""
    desc_path.write_text(json.dumps(desc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # config: ubrugte konstanter
    used_cfg = {t for f, t, k, _ in b.edges if k == "config"}
    for key, s in b.sym.items():
        if s["kind"] == "config":
            s["unused"] = key not in used_cfg

    used = set()
    ids = {k: slug(k, used) for k in b.sym}
    out_sym = {}
    for k, s in b.sym.items():
        s = dict(s)
        s["id"] = ids[k]
        s["parent"] = ids.get(s["parent"]) if s["parent"] is not None else None
        s["children"] = [ids[c] for c in s["children"]]
        s["missing"] = k in missing
        out_sym[ids[k]] = s
    edges = []
    seen = set()
    for f, t, kind, label in b.edges:
        if f in ids and t in ids and (f, t, kind, label) not in seen:
            seen.add((f, t, kind, label))
            edges.append({"from": ids[f], "to": ids[t], "kind": kind, "label": label})

    diagram = []
    for key, pos in desc.get("diagram", {}).items():
        if key in ids:
            diagram.append({"id": ids[key], "x": pos[0], "y": pos[1]})
        else:
            print(f"  ! diagram-nøgle findes ikke i koden: {key}")

    data = {
        "meta": {"repo_name": desc.get("repo_name", repo.name), "web": web, "commit": commit,
                 "commit_date": commit_date, "built": datetime.datetime.now().isoformat(timespec="minutes"),
                 "overview": desc.get("overview", {}), "stale": stale, "missing": [ids[k] for k in missing]},
        "root": ids[""],
        "symbols": out_sym,
        "edges": edges,
        "diagram": diagram,
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    template = (HERE / "template.html").read_text(encoding="utf-8")
    page = template.replace("/*__EXPLORER_DATA__*/null", payload)
    out = Path(args.out)
    out.write_text("<!doctype html>\n<html lang=\"da\"><head><meta charset=\"utf-8\">"
                   "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">"
                   "</head><body>\n" + page + "\n</body></html>\n", encoding="utf-8")
    (HERE / ".artifact_page.html").write_text(page, encoding="utf-8")

    n = lambda kind: sum(1 for s in b.sym.values() if s["kind"] == kind)
    print(f"Bygget {out}  ({len(page)//1024} KB)")
    print(f"  {n('file')} filer, {n('class')} klasser, {n('method')} metoder, {n('function')} funktioner, "
          f"{n('route')} routes, {n('config')} config-værdier, {len(edges)} forbindelser")
    if missing:
        print(f"  {len(missing)} mangler beskrivelse (tom skabelon lagt i descriptions.json):")
        for k in missing:
            print("    -", k)
    if stale:
        print(f"  {len(stale)} beskrivelser peger på kode der ikke findes mere:")
        for k in stale:
            print("    -", k)
    if args.check and missing:
        sys.exit(1)


if __name__ == "__main__":
    main()
