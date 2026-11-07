"""Versions and version ranges of packages and of the harness itself.

A version is MAJOR.MINOR.PATCH, optionally with a pre-release (`1.0.0-rc.1`); a shorter
one (`0.57`) has zeros for the parts it leaves out. A range is comparators joined by
commas, all of which must hold:

    >=0.57,<2       at least 0.57, below 2
    ^1.2            >=1.2.0,<2.0.0 (^0.3 is >=0.3.0,<0.4.0: below 1 the minor is the major)
    ~1.2            >=1.2.0,<1.3.0
    ==1.2.3, 1.2.3  exactly that version
    !=1.2.3         anything but it
    *, ""           any version

A pre-release satisfies a range only when the range names a pre-release itself, so
`harness install x` never picks one unless asked.
"""

from dataclasses import dataclass
import re


VERSION = re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-([0-9A-Za-z.-]+))?$")
COMPARATOR = re.compile(r"^(>=|<=|==|!=|>|<|\^|~)?\s*(\S+)$")


@dataclass(frozen=True, order=False)
class Version:
    major: int
    minor: int
    patch: int
    pre: str = ""

    @classmethod
    def parse(cls, text) -> "Version":
        match = VERSION.match(str(text).strip())
        if not match:
            raise ValueError(f"{text!r} is not a version (MAJOR.MINOR.PATCH)")
        major, minor, patch, pre = match.groups()
        return cls(int(major), int(minor or 0), int(patch or 0), pre or "")

    def key(self) -> tuple:
        # A release sorts after its pre-releases; pre-release parts compare as numbers
        # where they are numbers.
        parts = tuple((0, int(part), "") if part.isdigit() else (1, 0, part) for part in self.pre.split(".")) \
            if self.pre else ()
        return (self.major, self.minor, self.patch, 0 if self.pre else 1, parts)

    def __lt__(self, other):
        return self.key() < other.key()

    def __le__(self, other):
        return self.key() <= other.key()

    def __gt__(self, other):
        return self.key() > other.key()

    def __ge__(self, other):
        return self.key() >= other.key()

    def __str__(self):
        return f"{self.major}.{self.minor}.{self.patch}" + (f"-{self.pre}" if self.pre else "")


def _comparators(text: str) -> list[tuple[str, Version]]:
    out = []
    for part in (piece.strip() for piece in str(text or "").split(",")):
        if part in ("", "*"):
            continue
        match = COMPARATOR.match(part)
        if not match:
            raise ValueError(f"{text!r} is not a version range")
        operator, version = match.group(1) or "==", Version.parse(match.group(2))
        if operator == "^":
            upper = Version(version.major + 1, 0, 0) if version.major else \
                Version(0, version.minor + 1, 0) if version.minor else Version(0, 0, version.patch + 1)
            out += [(">=", version), ("<", upper)]
        elif operator == "~":
            out += [(">=", version), ("<", Version(version.major, version.minor + 1, 0))]
        else:
            out.append((operator, version))
    return out


def check_range(text) -> str:
    """The range as written, or ValueError."""
    _comparators(text)
    return str(text or "").strip()


def satisfies(version, text) -> bool:
    """Whether `version` is in range `text`."""
    version = version if isinstance(version, Version) else Version.parse(version)
    comparators = _comparators(text)
    if version.pre and not any(bound.pre for _, bound in comparators):
        return False
    tests = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b,
             "<": lambda a, b: a < b, "==": lambda a, b: a.key() == b.key(), "!=": lambda a, b: a.key() != b.key()}
    return all(tests[operator](version, bound) for operator, bound in comparators)


def best(versions, *ranges) -> str | None:
    """The highest of `versions` in every range; None when none is."""
    fitting = [Version.parse(version) for version in versions
               if all(satisfies(version, text) for text in ranges or ("",))]
    return str(max(fitting)) if fitting else None


def latest(versions) -> str | None:
    """The highest release among `versions` (else the highest pre-release)."""
    parsed = [Version.parse(version) for version in versions]
    releases = [version for version in parsed if not version.pre]
    return str(max(releases or parsed)) if parsed else None
