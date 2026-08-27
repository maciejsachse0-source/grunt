"""Interpretacja robots.txt z obsluga wildcardow.

Dlaczego nie urllib.robotparser z biblioteki standardowej: on porownuje sciezki
przez startswith i NIE ZNA znakow "*" ani "$". Caly robots.txt Morizona opiera
sie wlasnie na nich:

    Disallow: *page=*
    Allow: *page=2$
    ...
    Allow: *page=10$
    Disallow: *sort=*

Przy parserze standardowym reguly te nie pasuja do niczego, wiec "?page=11"
i "?sort=date" wychodza jako dozwolone, czyli dokladnie odwrotnie do intencji
serwisu. Sprawdzone na zywym pliku: standardowy parser przepuszczal oba adresy.

Implementujemy zasady z Robots Exclusion Protocol (RFC 9309):
* grupa dla naszego User-Agenta, a gdy jej brak, grupa "*";
* gdy nie ma zadnej pasujacej grupy, wszystko jest dozwolone;
* "*" zastepuje dowolny ciag, "$" oznacza koniec adresu;
* wygrywa regula o najdluzszym wzorcu, a przy remisie Allow bije Disallow.

Funkcje czyste, testowane na tresci robots.txt zapisanej w tests/fixtures.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class Rule:
    allow: bool
    pattern: str
    regex: re.Pattern[str]

    @property
    def length(self) -> int:
        """Dlugosc wzorca decyduje o pierwszenstwie regul (RFC 9309, 2.2.2)."""
        return len(self.pattern)


@dataclass
class Group:
    agents: list[str] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    crawl_delay: float | None = None


def _compile(pattern: str) -> re.Pattern[str]:
    """Wzorzec robots.txt na wyrazenie regularne.

    "*" to dowolny ciag, "$" na koncu to kotwica konca adresu. Wszystko inne
    jest traktowane doslownie, wiec znaki specjalne regexa trzeba wyescapowac.
    """
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    escaped = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    return re.compile(f"^{escaped}$" if anchored else f"^{escaped}")


def parse(text: str) -> list[Group]:
    groups: list[Group] = []
    current: Group | None = None
    poprzednia_linia_to_agent = False

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field_name, _, value = line.partition(":")
        field_name = field_name.strip().lower()
        value = value.strip()

        if field_name == "user-agent":
            if current is None or not poprzednia_linia_to_agent:
                current = Group()
                groups.append(current)
            current.agents.append(value.lower())
            poprzednia_linia_to_agent = True
            continue

        poprzednia_linia_to_agent = False
        if current is None:
            continue

        if field_name in ("allow", "disallow"):
            if field_name == "disallow" and value == "":
                # "Disallow:" bez wartosci oznacza brak ograniczen
                continue
            current.rules.append(
                Rule(allow=field_name == "allow", pattern=value, regex=_compile(value))
            )
        elif field_name == "crawl-delay":
            with contextlib.suppress(ValueError):
                current.crawl_delay = float(value.replace(",", "."))

    return groups


def _select_group(groups: list[Group], user_agent: str) -> Group | None:
    """Reguly dla naszego agenta, ze SCALENIEM grup o tym samym agencie.

    RFC 9309 punkt 2.2.1: grupy o tej samej nazwie agenta traktuje sie lacznie.
    To nie jest szczegol akademicki - robots.txt Morizona ma dwie osobne sekcje
    "User-agent: *" (druga po komentarzu "# re-frontend"). Branie tylko jednej
    z nich gubi polowe zakazow: w pierwszej jest "Disallow: /api", w drugiej
    reguly o paginacji i sortowaniu.
    """
    token = user_agent.split("/")[0].strip().lower()

    dopasowane = [g for g in groups if any(a != "*" and a in token for a in g.agents)]
    if not dopasowane:
        dopasowane = [g for g in groups if "*" in g.agents]
    if not dopasowane:
        return None

    scalona = Group(agents=[token or "*"])
    for group in dopasowane:
        scalona.rules.extend(group.rules)
        if group.crawl_delay is not None and scalona.crawl_delay is None:
            scalona.crawl_delay = group.crawl_delay
    return scalona


@dataclass
class Robots:
    groups: list[Group]
    user_agent: str

    @classmethod
    def from_text(cls, text: str, user_agent: str) -> Robots:
        return cls(groups=parse(text), user_agent=user_agent)

    @property
    def group(self) -> Group | None:
        return _select_group(self.groups, self.user_agent)

    @property
    def crawl_delay(self) -> float | None:
        group = self.group
        return group.crawl_delay if group else None

    def can_fetch(self, url: str) -> bool:
        group = self.group
        if group is None or not group.rules:
            return True

        parts = urlsplit(url)
        path = parts.path or "/"
        if parts.query:
            path = f"{path}?{parts.query}"

        najlepsza: Rule | None = None
        for rule in group.rules:
            # wzorzec z gwiazdka moze pasowac w srodku adresu, zwykly tylko od poczatku
            pasuje = rule.regex.search(path) if "*" in rule.pattern else rule.regex.match(path)
            wygrywa = (
                najlepsza is None
                or rule.length > najlepsza.length
                or (rule.length == najlepsza.length and rule.allow)
            )
            if pasuje and wygrywa:
                najlepsza = rule

        return najlepsza.allow if najlepsza else True
