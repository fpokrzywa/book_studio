"""Convert the LaTeX math used in BookMD into Typst math for the print PDF.

It covers the common subset (fractions, roots, scripts, Greek letters, operators, relations, big
operators, accents, \\text, \\mathrm, \\left/\\right, matrices with &/\\\\ in a few environments).
Anything it does not understand raises UnsupportedMath; the writer then prints the LaTeX source in a
code style and the export report lists the equation, so an equation is never silently lost.
"""

from __future__ import annotations

import re

_GREEK = {
    "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa", "lambda", "mu", "nu",
    "xi", "omicron", "pi", "rho", "sigma", "tau", "upsilon", "phi", "chi", "psi", "omega",
}  # fmt: skip
_SYMBOLS = {
    "varepsilon": "epsilon.alt", "vartheta": "theta.alt", "varphi": "phi.alt", "varpi": "pi.alt",
    "varrho": "rho.alt", "varsigma": "sigma.alt",
    "cdot": "dot.op", "times": "times", "div": "div", "pm": "plus.minus", "mp": "minus.plus", "ast": "ast",
    "le": "<=", "leq": "<=", "ge": ">=", "geq": ">=", "neq": "!=", "ne": "!=", "approx": "approx",
    "equiv": "equiv", "sim": "tilde.op", "simeq": "tilde.eq", "propto": "prop", "ll": "<<", "gg": ">>",
    "in": "in", "notin": "in.not", "subset": "subset", "subseteq": "subset.eq", "supset": "supset",
    "cup": "union", "cap": "sect", "emptyset": "emptyset", "forall": "forall", "exists": "exists",
    "infty": "infinity", "partial": "diff", "nabla": "nabla", "to": "->", "rightarrow": "->",
    "leftarrow": "<-", "Rightarrow": "=>", "Leftarrow": "arrow.l.double", "leftrightarrow": "<->",
    "mapsto": "|->", "ldots": "dots.h", "cdots": "dots.c", "dots": "dots.h", "vdots": "dots.v",
    "prime": "prime", "circ": "compose", "angle": "angle", "degree": "degree", "hbar": "planck.reduce",
    "ell": "ell", "Re": "Re", "Im": "Im", "neg": "not", "land": "and", "lor": "or", "quad": "quad",
    "qquad": "wide", ",": "thin", ";": "med", "!": "", " ": "space",
    "sum": "sum", "prod": "product", "int": "integral", "iint": "integral.double", "oint": "integral.cont",
    "lim": "lim", "max": "max", "min": "min", "sup": "sup", "inf": "inf", "log": "log", "ln": "ln",
    "exp": "exp", "sin": "sin", "cos": "cos", "tan": "tan", "det": "det", "gcd": "gcd",
    "langle": "angle.l", "rangle": "angle.r", "lfloor": "floor.l", "rfloor": "floor.r", "lceil": "ceil.l",
    "rceil": "ceil.r", "{": "{", "}": "}", "|": "||", "%": "%", "#": "\\#", "$": "\\$", "_": "\\_", "&": "\\&",
}  # fmt: skip
_ACCENTS = {"hat": "hat", "bar": "overline", "overline": "overline", "vec": "arrow", "dot": "dot",
            "ddot": "dot.double", "tilde": "tilde", "underline": "underline", "widehat": "hat"}  # fmt: skip
_FONTS = {"mathrm": "upright", "mathbf": "bold", "mathit": "italic", "mathbb": "bb", "mathcal": "cal",
          "mathsf": "sans", "mathtt": "mono", "operatorname": "op", "boldsymbol": "bold"}  # fmt: skip
_TOKEN = re.compile(r"\\[A-Za-z]+|\\.|[{}^_&]|\s+|[A-Za-z]|\d+(?:\.\d+)?|.", re.S)


class UnsupportedMath(ValueError):
    pass


class _P:
    def __init__(self, tex: str) -> None:
        self.toks = [t for t in _TOKEN.findall(tex)]
        self.i = 0

    def peek(self) -> str | None:
        while self.i < len(self.toks) and self.toks[self.i].isspace():
            self.i += 1
        return self.toks[self.i] if self.i < len(self.toks) else None

    def take(self) -> str:
        t = self.peek()
        if t is None:
            raise UnsupportedMath("unexpected end")
        self.i += 1
        return t

    def group(self) -> str:
        """A braced group or a single atom, converted."""
        t = self.peek()
        if t == "{":
            self.take()
            out = self.seq(stop="}")
            self.take()
            return out
        return self.atom()

    def raw_group(self) -> str:
        if self.take() != "{":
            raise UnsupportedMath("expected {")
        depth, out = 1, list[str]()
        while self.i < len(self.toks):
            t = self.toks[self.i]
            self.i += 1
            if t == "{":
                depth += 1
            elif t == "}":
                depth -= 1
                if depth == 0:
                    return "".join(out)
            out.append(t)
        raise UnsupportedMath("unbalanced braces")

    def seq(self, stop: str | None = None) -> str:
        parts: list[str] = []
        while True:
            t = self.peek()
            if t is None or t == stop or (stop == "\\right" and t == "\\right"):
                break
            if stop is None and t == "}":
                raise UnsupportedMath("unbalanced }")
            parts.append(self.atom())
        return " ".join(p for p in parts if p)

    def atom(self) -> str:
        t = self.take()
        if t in ("^", "_"):
            return t + "(" + self.group() + ")"
        if t == "{":
            out = self.seq(stop="}")
            self.take()
            return "(" + out + ")" if out else ""
        if t == "&":
            return "&"
        if t.startswith("\\"):
            return self.command(t[1:])
        if re.fullmatch(r"[A-Za-z]", t):
            return t
        if re.fullmatch(r"\d+(?:\.\d+)?", t):
            return t
        if t in "+-=<>()[],.;:!/|'*":
            return {"*": "ast"}.get(t, t)
        raise UnsupportedMath(f"character {t!r}")

    def command(self, name: str) -> str:
        if name == "\\":
            return ";"  # row break inside a matrix
        if name in ("frac", "dfrac", "tfrac"):
            a = self.group()
            b = self.group()
            return f"frac({a}, {b})"
        if name == "sqrt":
            if self.peek() == "[":
                self.take()
                n = self.seq(stop="]")
                self.take()
                return f"root({n}, {self.group()})"
            return f"sqrt({self.group()})"
        if name in ("text", "textrm", "mbox"):
            s = self.raw_group().replace("\\", "\\\\").replace('"', '\\"')
            return f'"{s}"'
        if name in _FONTS:
            return f"{_FONTS[name]}({self.group()})"
        if name in _ACCENTS:
            return f"{_ACCENTS[name]}({self.group()})"
        if name in ("left", "right"):
            d = self.take()
            if d == "\\":
                d = self.take()
            return {".": "", "\\{": "{", "\\}": "}", "\\|": "||", "\\langle": "angle.l", "\\rangle": "angle.r"}.get(
                d, d
            )
        if name == "begin":
            env = self.raw_group()
            if env not in ("matrix", "pmatrix", "bmatrix", "vmatrix", "cases", "aligned", "align*", "align"):
                raise UnsupportedMath(f"environment {env}")
            body: list[str] = []
            while True:
                if self.peek() is None:
                    raise UnsupportedMath("unterminated environment")
                if self.peek() == "\\end":
                    self.take()
                    self.raw_group()
                    break
                body.append(self.atom())
            rows = [r.strip() for r in " ".join(body).split(";")]
            if env == "cases":
                return "cases(" + ", ".join(r.replace("&", "") for r in rows if r) + ")"
            if env in ("aligned", "align*", "align"):
                return " \\ ".join(rows)
            delim = {"matrix": "#none", "pmatrix": '"("', "bmatrix": '"["', "vmatrix": '"|"'}[env]
            cells = "; ".join(", ".join(c.strip() for c in r.split("&")) for r in rows if r)
            return f"mat(delim: {delim}, {cells})"
        if name in _GREEK:
            return name
        if name[:1].isupper() and name.lower() in _GREEK:
            return name[0] + name[1:]
        if name in _SYMBOLS:
            return _SYMBOLS[name]
        raise UnsupportedMath(f"\\{name}")


def to_typst(tex: str) -> str:
    """Typst math content (without the surrounding $ $). Raises UnsupportedMath."""
    p = _P(tex)
    out = p.seq()
    if p.peek() is not None:
        raise UnsupportedMath("trailing input")
    return out
