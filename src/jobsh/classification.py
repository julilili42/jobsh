"""Conservative IT classification; the first matching rule wins."""

import re

NON_IT = r"\b(recruit\w*|personalreferent\w*|talent acquisition|sales|vertrieb\w*|marketing|buchhalt\w*|accountant|pflege\w*|nurse|koch|cook|business development)\b"
IT_ROLE = r"\b(softwareentwickler\w*|software developer|software engineer|programmierer\w*|fachinformatiker\w*|systemadministrator\w*|sysadmin|devops|sre|data engineer|data scientist|frontend\w*|backend\w*|full.?stack|it[ -](support|administrator|security|architect)|cybersecurity)\b"
TECH = r"(?<!\w)(python|java|javascript|typescript|golang|go|c\+\+|c#|\.net|sql|linux|kubernetes)(?!\w)"
GENERIC_ROLE = r"\b(developer|entwickler\w*|engineer|administrator)\b"


def classify(title: str, description: str = "", source_category: str = "") -> tuple[str, str]:
    if re.search(NON_IT, title, re.I):
        return "non_it", "title:non_it_role"
    if re.search(IT_ROLE, title, re.I):
        return "it", "title:it_role"
    if re.search(GENERIC_ROLE, title, re.I):
        if re.search(TECH, title, re.I):
            return "it", "title:technical_role"
        if re.search(r"\b(it|software|information technology|informatik)\b", source_category, re.I):
            return "it", "category:it_with_role"
        if re.search(IT_ROLE, description, re.I) and re.search(TECH, description, re.I):
            return "it", "description:it_role_and_technology"
    return "uncertain", "unmatched"
