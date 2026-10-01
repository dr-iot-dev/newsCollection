"""RFC 9309 matching: merged groups, longest rule, Allow on ties."""

import re
from urllib.parse import quote, urlsplit

from app.modules.acquisition.http import CollectionError


def octets(value: str) -> str:
    # Decode only percent-encoded unreserved bytes; reserved bytes stay encoded.
    def replace(match: re.Match[str]) -> str:
        char = chr(int(match[1], 16))
        return char if char.isascii() and (char.isalnum() or char in "-._~") else match[0].upper()

    return re.sub(r"%([0-9a-fA-F]{2})", replace, quote(value, safe="/%*?$=&;:+,@!()-._~"))


class RobotsPolicy:
    def __init__(self, body: str, user_agent: str) -> None:
        if not body.strip() or "<html" in body.lower() or "<!doctype html" in body.lower():
            raise CollectionError("ROBOTS_INVALID")
        groups: list[tuple[list[str], list[tuple[str, bool]], float]] = []
        agents: list[str] = []
        rules: list[tuple[str, bool]] = []
        delay = 0.0
        started = False
        for line in body.lstrip("\ufeff").splitlines():
            line = line.split("#", 1)[0].strip()
            key, sep, value = line.partition(":")
            if not sep:
                continue
            key, value = key.lower().strip(), value.strip()
            if key == "user-agent":
                if started:
                    groups.append((agents, rules, delay))
                    agents, rules, delay, started = [], [], 0.0, False
                agents.append(value.lower())
            elif agents and key in {"allow", "disallow"}:
                started = True
                if value:
                    if not value.startswith("/"):
                        raise CollectionError("ROBOTS_INVALID")
                    rules.append((octets(value), key == "allow"))
            elif agents and key == "crawl-delay":
                started = True
                try:
                    delay = max(delay, float(value))
                except ValueError:
                    raise CollectionError("ROBOTS_INVALID") from None
        if agents:
            groups.append((agents, rules, delay))
        agent = user_agent.split("/", 1)[0].lower()
        matches = [group for group in groups if agent in group[0]]
        if not matches:
            matches = [group for group in groups if "*" in group[0]]
        self.rules = [rule for _, group_rules, _ in matches for rule in group_rules]
        self.delay = max((group_delay for _, _, group_delay in matches), default=0.0)
        if not 0 <= self.delay <= 60:
            raise CollectionError("ROBOTS_CRAWL_DELAY_UNSUPPORTED")

    def allowed(self, url: str) -> bool:
        parsed = urlsplit(url)
        target = octets(parsed.path or "/")
        if parsed.query:
            target += "?" + octets(parsed.query)
        matching: list[tuple[int, bool]] = []
        for rule, allow in self.rules:
            ending = rule.endswith("$")
            pattern = rule[:-1] if ending else rule
            expression = "^" + ".*".join(re.escape(part) for part in pattern.split("*"))
            if ending:
                expression += "$"
            if re.search(expression, target):
                matching.append((len(pattern.encode()), allow))
        return max(matching)[1] if matching else True
