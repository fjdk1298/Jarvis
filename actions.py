"""Local actions and lightweight web-intel helpers for Jarvis.

This module handles direct PC actions and local web retrieval so Jarvis
can remain useful even when upstream model credits are limited.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import urllib.parse
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ActionResult:
    """Result payload for local command handling."""

    handled: bool
    response: str | None = None


_WINDOWS_APP_ALIASES = {
    "whatsapp": "WhatsApp",
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "firefox": "firefox.exe",
    "spotify": "Spotify",
    "vscode": "code",
    "visual studio code": "code",
    "discord": "Discord",
    "telegram": "Telegram",
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "terminal": "cmd.exe",
    "command prompt": "cmd.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
    "paint": "mspaint.exe",
    "word": "winword.exe",
    "excel": "excel.exe",
    "powerpoint": "powerpnt.exe",
    "vlc": "vlc.exe",
    "zoom": "Zoom",
    "slack": "Slack",
    "steam": "steam.exe",
    "task manager": "taskmgr.exe",
    "settings": "ms-settings:",
    "edge": "msedge.exe",
    "brave": "brave.exe",
    "obsidian": "Obsidian",
    "notion": "Notion",
    "github": "https://github.com",
    "calendar": "outlookcal:",
}

_WINDOWS_PROCESS_ALIASES = {
    "whatsapp": "WhatsApp.exe",
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "firefox": "firefox.exe",
    "spotify": "Spotify.exe",
    "vscode": "Code.exe",
    "visual studio code": "Code.exe",
    "discord": "Discord.exe",
    "telegram": "Telegram.exe",
    "notepad": "notepad.exe",
    "calculator": "CalculatorApp.exe",
    "calc": "CalculatorApp.exe",
    "terminal": "WindowsTerminal.exe",
    "command prompt": "cmd.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
    "paint": "mspaint.exe",
    "word": "WINWORD.EXE",
    "excel": "EXCEL.EXE",
    "powerpoint": "POWERPNT.EXE",
    "vlc": "vlc.exe",
    "zoom": "Zoom.exe",
    "slack": "slack.exe",
    "steam": "steam.exe",
    "edge": "msedge.exe",
    "brave": "brave.exe",
    "obsidian": "Obsidian.exe",
    "notion": "Notion.exe",
}

_BASE_DIR = Path(__file__).resolve().parent
_ACTIVITY_LOG_PATH = _BASE_DIR / "data" / "activity_log.json"
_SEARCHABLE_SITES = ("youtube", "google", "github", "reddit", "netflix", "wikipedia")
_SITE_URL_ALIASES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "netflix": "https://www.netflix.com",
    "disney plus": "https://www.disneyplus.com",
    "disney+": "https://www.disneyplus.com",
    "prime video": "https://www.primevideo.com",
    "amazon prime": "https://www.primevideo.com",
    "hbo max": "https://play.max.com",
    "max": "https://play.max.com",
    "twitch": "https://www.twitch.tv",
    "spotify web": "https://open.spotify.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "linkedin": "https://www.linkedin.com",
    "tiktok": "https://www.tiktok.com",
    "wikipedia": "https://www.wikipedia.org",
    "maps": "https://maps.google.com",
    "google maps": "https://maps.google.com",
    "gmail": "https://mail.google.com",
    "mail": "https://mail.google.com",
    "mails": "https://mail.google.com",
    "email": "https://mail.google.com",
    "emails": "https://mail.google.com",
    "inbox": "https://mail.google.com",
    "letters": "https://mail.google.com",
    "github": "https://github.com",
    "reddit": "https://www.reddit.com",
}


def get_runtime_time_context() -> str:
    """Return a concise local date/time string for response grounding."""
    now = dt.datetime.now().astimezone()
    return now.strftime("%A, %B %d, %Y %H:%M %Z")


def _normalize_url(target: str) -> str:
    """Normalize a target into a browsable URL when possible."""
    cleaned = target.strip().strip('"').strip("'")
    if cleaned.startswith(("http://", "https://")):
        return cleaned
    if "." in cleaned and " " not in cleaned:
        return f"https://{cleaned}"
    return cleaned


def _split_browser_preference(text: str) -> tuple[str, str | None]:
    """Strip trailing browser preference hints like 'in chrome' from a command."""
    match = re.search(r"\s+in\s+(google\s+chrome|chrome|edge|firefox|brave)\s*$", text, flags=re.IGNORECASE)
    if not match:
        return text.strip(), None
    browser = match.group(1).lower().strip()
    cleaned = text[: match.start()].strip()
    return cleaned, browser


def _resolve_app_alias(target: str) -> str | None:
    """Resolve app name to a Windows launch target with fuzzy alias support."""
    normalized = target.lower().strip()
    if normalized in _WINDOWS_APP_ALIASES:
        return _WINDOWS_APP_ALIASES[normalized]

    for alias, resolved in _WINDOWS_APP_ALIASES.items():
        if alias in normalized or normalized in alias:
            return resolved

    return None


def _resolve_site_alias(target: str) -> str | None:
    """Resolve friendly website names into launchable URLs."""
    normalized = target.lower().strip()
    if normalized in _SITE_URL_ALIASES:
        return _SITE_URL_ALIASES[normalized]

    for alias, resolved in _SITE_URL_ALIASES.items():
        if alias in normalized or normalized in alias:
            return resolved

    return None


def _resolve_process_alias(target: str) -> str | None:
    """Resolve friendly app names into Windows process image names."""
    normalized = target.lower().strip()
    if normalized in _WINDOWS_PROCESS_ALIASES:
        return _WINDOWS_PROCESS_ALIASES[normalized]

    for alias, resolved in _WINDOWS_PROCESS_ALIASES.items():
        if alias in normalized or normalized in alias:
            return resolved

    if normalized.endswith(".exe"):
        return normalized

    if normalized and " " not in normalized:
        return f"{normalized}.exe"

    return None


def _open_windows_target(target: str) -> bool:
    """Open an app, file, URI, or executable via Windows start."""
    try:
        subprocess.Popen(["cmd", "/c", "start", "", target], shell=False)
        return True
    except Exception:
        return False


def _open_url(url: str, preferred_browser: str | None = None) -> bool:
    """Open a URL, optionally preferring a specific installed browser."""
    if preferred_browser in {"chrome", "google chrome"}:
        chrome_target = _resolve_app_alias("chrome")
        if chrome_target:
            try:
                subprocess.Popen(["cmd", "/c", "start", "", chrome_target, url], shell=False)
                return True
            except Exception:
                pass

    if preferred_browser == "edge":
        edge_target = _resolve_app_alias("edge")
        if edge_target:
            try:
                subprocess.Popen(["cmd", "/c", "start", "", edge_target, url], shell=False)
                return True
            except Exception:
                pass

    return webbrowser.open(url)


def _close_windows_target(process_name: str) -> bool:
    """Close a running app process using taskkill."""
    try:
        completed = subprocess.run(
            ["taskkill", "/IM", process_name, "/F"],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
        if completed.returncode == 0:
            return True
        stderr = (completed.stderr or "").lower()
        stdout = (completed.stdout or "").lower()
        if "not found" in stderr or "no running instance" in stdout:
            return False
        return False
    except Exception:
        return False


def _get_outlook_todays_events(max_items: int = 5) -> list[dict[str, str]]:
    """Read today's Outlook calendar items if Outlook integration is available."""
    try:
        import win32com.client

        outlook = win32com.client.Dispatch("Outlook.Application")
        namespace = outlook.GetNamespace("MAPI")
        calendar_folder = namespace.GetDefaultFolder(9)
        items = calendar_folder.Items
        items.Sort("[Start]")
        items.IncludeRecurrences = True

        local_now = dt.datetime.now().astimezone()
        day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + dt.timedelta(days=1)

        start_filter = day_start.strftime("%m/%d/%Y %I:%M %p")
        end_filter = day_end.strftime("%m/%d/%Y %I:%M %p")
        restriction = f"[Start] >= '{start_filter}' AND [Start] < '{end_filter}'"

        restricted = items.Restrict(restriction)
        events: list[dict[str, str]] = []
        for index in range(1, min(restricted.Count, max_items) + 1):
            appointment = restricted.Item(index)
            subject = str(getattr(appointment, "Subject", "")).strip() or "Untitled event"
            start = getattr(appointment, "Start", None)
            start_text = ""
            if start:
                try:
                    start_text = dt.datetime.fromtimestamp(int(start.timestamp())).strftime("%H:%M")
                except Exception:
                    start_text = str(start)
            events.append({"subject": subject, "start": start_text})
        return events
    except Exception:
        return []


def _record_activity(kind: str, command: str) -> None:
    """Persist lightweight activity history for later recall prompts."""
    try:
        _ACTIVITY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        rows: list[dict[str, str]] = []
        if _ACTIVITY_LOG_PATH.exists():
            payload = json.loads(_ACTIVITY_LOG_PATH.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict):
                        rows.append(
                            {
                                "ts": str(item.get("ts", "")),
                                "kind": str(item.get("kind", "")),
                                "command": str(item.get("command", "")),
                            }
                        )

        rows.append(
            {
                "ts": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                "kind": kind,
                "command": command.strip(),
            }
        )
        rows = rows[-80:]
        _ACTIVITY_LOG_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return


def _recent_activity_brief(limit: int = 5) -> str:
    """Return a spoken summary of recent remembered local activities."""
    if not _ACTIVITY_LOG_PATH.exists():
        return "I do not have any recent local activity recorded yet, sir."

    try:
        payload = json.loads(_ACTIVITY_LOG_PATH.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            return "I do not have any recent local activity recorded yet, sir."

        rows: list[str] = []
        for item in payload[-limit:]:
            if not isinstance(item, dict):
                continue
            ts = str(item.get("ts", "")).replace("T", " ")
            kind = str(item.get("kind", "activity"))
            command = str(item.get("command", "")).strip()
            if command:
                rows.append(f"{kind} at {ts}: {command}")

        if not rows:
            return "I do not have any recent local activity recorded yet, sir."

        joined = " Then ".join(rows)
        return f"Here is your recent activity log, sir. {joined}."
    except Exception:
        return "I could not read the activity history just now, sir."


def _search_web_rows(query: str, max_results: int = 3) -> list[dict[str, str]]:
    """Fetch raw web search rows using DDGS-compatible providers."""
    try:
        try:
            from ddgs import DDGS
        except Exception:
            from duckduckgo_search import DDGS

        rows: list[dict[str, str]] = []
        with DDGS() as ddgs:
            for item in ddgs.text(query, max_results=max_results):
                rows.append(
                    {
                        "title": (item.get("title") or "").strip(),
                        "snippet": (item.get("body") or "").strip(),
                        "url": (item.get("href") or "").strip(),
                    }
                )
        return rows
    except Exception as exc:
        print(f"[INFO] Live web lookup unavailable: {exc}")
        return []


def _build_web_brief(query: str, rows: list[dict[str, str]]) -> str:
    """Create a short spoken summary from search rows."""
    if not rows:
        return "I could not retrieve live web results right now, sir."

    top = rows[:2]
    first = top[0]
    first_line = first.get("snippet") or first.get("title") or "I found relevant results."

    if len(top) == 1:
        return f"Here is the latest I found, sir. {first_line}"

    second = top[1]
    second_line = second.get("snippet") or second.get("title") or "There is also another useful source."
    return f"Here is a quick web brief, sir. {first_line} Another source adds this: {second_line}"


def _extract_search_query(command: str) -> str | None:
    """Extract web-search intent from natural language command patterns."""
    patterns = [
        r"^(?:can you|could you|would you|please)?\s*search(?:\s+on)?(?:\s+google|\s+the\s+web|\s+the\s+internet|\s+online)?\s+(?:for\s+)?(.+)$",
        r"^(?:please\s+)?search\s+(?:for\s+)?(.+)$",
        r"^(?:can you|could you|would you|please)?\s*google\s+(.+)$",
        r"^(?:please\s+)?search\s+google\s+(?:for\s+)?(.+)$",
        r"^(?:please\s+)?look\s+up\s+(.+)$",
        r"^(?:please\s+)?find\s+on\s+the\s+web\s+(.+)$",
        r"^(?:what(?:'s| is)\s+the\s+latest\s+on\s+)(.+)$",
        r"^(?:latest\s+news\s+about\s+)(.+)$",
    ]

    text = command.strip()
    for pattern in patterns:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip(" .?!")
            if value:
                return value
    return None


def _extract_site_search(command: str) -> tuple[str, str, str | None] | None:
    """Extract site-specific search intent like YouTube or Google queries."""
    text, browser_preference = _split_browser_preference(command.strip())
    site_pattern = "|".join(re.escape(site) for site in _SEARCHABLE_SITES)
    patterns = [
        rf"^(?:can you|could you|would you|please)?\s*(?:search|look up|find)\s+(?:on\s+)?({site_pattern})\s+(?:for\s+)?(.+)$",
        rf"^(?:please\s+)?(?:open\s+)?({site_pattern})\s+(?:and\s+)?search\s+(?:for\s+)?(.+)$",
        rf"^(?:can you|could you|would you|please)?\s*(?:search|look up|find)\s+(?:for\s+)?(.+?)\s+on\s+({site_pattern})$",
        rf"^(?:please\s+)?(?:search\s+)?({site_pattern})\s+for\s+(.+)$",
        rf"^(?:please\s+)?(?:search\s+)?({site_pattern})\s+(.+)$",
    ]

    for pattern in patterns:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue

        first = match.group(1).strip(" .?!")
        second = match.group(2).strip(" .?!")
        if first.lower() in _SITE_URL_ALIASES:
            site = first.lower()
            query = second
        else:
            site = second.lower()
            query = first

        if query:
            return site, query, browser_preference
    return None


def _build_site_search_url(site: str, query: str) -> str | None:
    """Build a site-specific search URL."""
    encoded = urllib.parse.quote_plus(query.strip())
    if not encoded:
        return None

    site_key = site.lower().strip()
    if site_key == "youtube":
        return f"https://www.youtube.com/results?search_query={encoded}"
    if site_key == "google":
        return f"https://www.google.com/search?q={encoded}"
    if site_key == "github":
        return f"https://github.com/search?q={encoded}"
    if site_key == "reddit":
        return f"https://www.reddit.com/search/?q={encoded}"
    if site_key == "netflix":
        return f"https://www.netflix.com/search?q={encoded}"
    if site_key == "wikipedia":
        return f"https://en.wikipedia.org/w/index.php?search={encoded}"
    return None


def _friendly_site_name(site: str) -> str:
    """Return a nicely spoken site name."""
    labels = {
        "youtube": "YouTube",
        "google": "Google",
        "github": "GitHub",
        "reddit": "Reddit",
        "netflix": "Netflix",
        "disney plus": "Disney Plus",
        "disney+": "Disney Plus",
        "prime video": "Prime Video",
        "amazon prime": "Prime Video",
        "hbo max": "Max",
        "max": "Max",
        "twitch": "Twitch",
        "spotify web": "Spotify",
        "twitter": "X",
        "x": "X",
        "instagram": "Instagram",
        "facebook": "Facebook",
        "linkedin": "LinkedIn",
        "tiktok": "TikTok",
        "wikipedia": "Wikipedia",
        "maps": "Google Maps",
        "google maps": "Google Maps",
        "gmail": "Gmail",
        "mail": "Gmail",
        "mails": "Gmail",
        "email": "Gmail",
        "emails": "Gmail",
        "inbox": "Gmail",
        "letters": "Gmail",
    }
    return labels.get(site.lower().strip(), site.title())


def _is_search_capability_prompt(command: str) -> bool:
    """Detect search ability questions that do not yet include a real query."""
    normalized = re.sub(r"\s+", " ", command.lower().strip(" .?!"))
    prompts = {
        "can you search on google",
        "can you search google",
        "can you search the web",
        "can you search online",
        "can you google things",
        "can you google stuff",
        "can you look things up",
        "can you search the internet",
        "are you able to search on google",
        "are you able to search the web",
        "can you browse the web",
        "can you search on youtube",
        "can you search youtube",
        "can you search on github",
        "can you search github",
        "can you search netflix",
        "can you search on netflix",
        "can you search wikipedia",
        "can you search on wikipedia",
    }
    return normalized in prompts


def _open_google_results(query: str) -> bool:
    """Open a Google search results page for the given query."""
    encoded = urllib.parse.quote_plus(query.strip())
    if not encoded:
        return False
    return _open_url(f"https://www.google.com/search?q={encoded}")


def handle_local_action(command: str) -> ActionResult:
    """Handle direct local actions and lightweight factual requests."""
    text = command.strip()
    lower = text.lower()

    if any(phrase in lower for phrase in ["how are you", "how are you doing", "how do you feel"]):
        return ActionResult(True, "Operating smoothly and ready to assist, sir.")

    if any(phrase in lower for phrase in ["who are you", "what are you", "are you jarvis"]):
        return ActionResult(True, "I am Jarvis, your voice assistant, online and listening.")

    if any(phrase in lower for phrase in ["what can you do", "what are your capabilities", "help me"]):
        return ActionResult(
            True,
            "I can answer questions, search the web, open apps on this PC, open sites like YouTube, Netflix, or Gmail, and search directly on sites like Google or YouTube.",
        )

    if _is_search_capability_prompt(text):
        return ActionResult(
            True,
            "Yes sir. Tell me what to search for and I can open Google, YouTube, Netflix, GitHub, Reddit, or Wikipedia results, or give you a quick web brief.",
        )

    if ("open" in lower and "close" in lower and "app" in lower) or (
        any(prefix in lower for prefix in ["can you", "could you", "are you able to"])
        and ("open" in lower or "close" in lower)
    ):
        return ActionResult(
            True,
            "Yes sir. I can open and close apps for you. For example, say open Chrome or close Discord.",
        )

    if any(phrase in lower for phrase in ["thank you", "thanks", "nice work"]):
        return ActionResult(True, "Always a pleasure, sir.")

    if re.search(r"^(?:hey\s+)?jarvis[.!? ]*$", lower):
        return ActionResult(True, "Yes sir, I'm here.")

    if any(
        phrase in lower
        for phrase in [
            "what was i doing",
            "what did i do",
            "recent activity",
            "activity history",
            "what was i working on",
        ]
    ):
        return ActionResult(True, _recent_activity_brief(limit=4))

    if any(
        phrase in lower
        for phrase in [
            "today's list",
            "todays list",
            "what is on my calendar",
            "what's on my calendar",
            "what is on my schedule",
            "what's on my schedule",
        ]
    ):
        events = _get_outlook_todays_events(max_items=4)
        if not events:
            return ActionResult(
                True,
                "I could not read Outlook events right now, sir. If Outlook is connected, try opening Outlook once and ask again.",
            )
        spoken = []
        for event in events:
            subject = event.get("subject", "Untitled event")
            start = event.get("start", "")
            if start:
                spoken.append(f"{start}, {subject}")
            else:
                spoken.append(subject)
        summary = " ; ".join(spoken)
        return ActionResult(True, f"Today on your calendar, sir: {summary}.")

    if any(phrase in lower for phrase in ["what year is it", "which year is it", "current year"]) or re.search(
        r"\bwhat year\b", lower
    ):
        year = dt.datetime.now().astimezone().year
        return ActionResult(True, f"It is {year}, sir.")

    if any(phrase in lower for phrase in ["what date is it", "today's date", "todays date"]) or re.search(
        r"\bwhat date\b", lower
    ):
        date_text = dt.datetime.now().astimezone().strftime("%A, %B %d, %Y")
        return ActionResult(True, f"Today is {date_text}, sir.")

    if any(phrase in lower for phrase in ["what time is it", "current time"]) or re.search(r"\bwhat time\b", lower):
        time_text = dt.datetime.now().astimezone().strftime("%H:%M")
        return ActionResult(True, f"It is {time_text}, sir.")

    site_search = _extract_site_search(text)
    if site_search:
        site, query, browser_preference = site_search
        url = _build_site_search_url(site, query)
        if url and _open_url(url, preferred_browser=browser_preference):
            _record_activity("search", text)
            return ActionResult(True, f"Searching {_friendly_site_name(site)} for {query}, sir.")
        return ActionResult(True, f"I could not open {_friendly_site_name(site)} search right now, sir.")

    web_query = _extract_search_query(text)
    if web_query:
        _record_activity("search", text)
        if "google" in lower and _open_google_results(web_query):
            return ActionResult(True, f"Searching Google for {web_query}, sir.")
        rows = _search_web_rows(web_query, max_results=3)
        return ActionResult(True, _build_web_brief(web_query, rows))

    close_match = re.match(r"^(?:please\s+)?(?:close|quit|exit|stop)\s+(.+)$", text, flags=re.IGNORECASE)
    if close_match:
        target_raw = close_match.group(1).strip()
        target = target_raw.lower().strip()

        if target in {"jarvis", "yourself", "assistant"}:
            return ActionResult(False)

        resolved_process = _resolve_process_alias(target)
        if resolved_process and _close_windows_target(resolved_process):
            _record_activity("close", text)
            return ActionResult(True, f"Closing {target}, sir.")
        return ActionResult(True, f"I could not close {target} right now, sir.")

    open_match = re.match(r"^(?:please\s+)?(?:open|launch|start)\s+(.+)$", text, flags=re.IGNORECASE)
    if not open_match:
        return ActionResult(False)

    target_raw = open_match.group(1).strip()
    target_clean, browser_preference = _split_browser_preference(target_raw)
    target = target_clean.lower().strip()

    resolved = _resolve_app_alias(target)
    if resolved:
        if resolved.startswith("ms-settings:"):
            _record_activity("open", text)
            if webbrowser.open(resolved):
                return ActionResult(True, f"Opening {target}, sir.")
            return ActionResult(True, f"I could not open {target} just now, sir.")

        _record_activity("open", text)
        if _open_windows_target(resolved):
            return ActionResult(True, f"Opening {target}, sir.")
        return ActionResult(True, f"I could not open {target} just now, sir.")

    site_url = _resolve_site_alias(target)
    if site_url:
        _record_activity("open", text)
        if _open_url(site_url, preferred_browser=browser_preference):
            return ActionResult(True, f"Opening {_friendly_site_name(target)}, sir.")
        return ActionResult(True, f"I could not open {_friendly_site_name(target)} right now, sir.")

    normalized_url = _normalize_url(target_clean)
    if normalized_url.startswith(("http://", "https://")):
        _record_activity("open", text)
        if _open_url(normalized_url, preferred_browser=browser_preference):
            return ActionResult(True, "Opening that now, sir.")
        return ActionResult(True, "I could not open that page right now, sir.")

    _record_activity("open", text)
    if _open_windows_target(target_clean):
        return ActionResult(True, f"Opening {target_clean}, sir.")

    return ActionResult(True, f"I could not open {target_clean} on this machine, sir.")


def should_fetch_web_context(user_text: str) -> bool:
    """Heuristically decide whether the user request needs live web data."""
    if _extract_search_query(user_text) or _extract_site_search(user_text):
        return False

    lower = user_text.lower()
    triggers = [
        "today",
        "latest",
        "current",
        "news",
        "weather",
        "price",
        "stock",
        "score",
        "update",
        "look up",
        "who is",
        "what is",
        "what are",
        "how do",
        "how does",
        "why is",
        "why are",
        "when is",
        "internet",
    ]
    if any(token in lower for token in triggers):
        return True
    return lower.startswith(("who ", "what ", "when ", "where ", "why ", "how "))


def get_live_web_context(query: str, max_results: int = 3) -> Optional[str]:
    """Fetch compact web snippets for time-sensitive questions."""
    rows = _search_web_rows(query, max_results=max_results)
    if not rows:
        return None

    lines: list[str] = []
    for row in rows:
        title = row.get("title", "")
        snippet = row.get("snippet", "")
        url = row.get("url", "")
        if not title and not snippet:
            continue
        lines.append(f"- {title} | {snippet} | {url}")

    if not lines:
        return None

    return "\n".join(lines)
