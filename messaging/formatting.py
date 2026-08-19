import re

from django.core.exceptions import ValidationError


PLACEHOLDER_NAMES = (
    "#appointment_date",
    "#appointment_time",
    "#doctor",
    "#department",
    "#patient_name",
    "#mrn",
    "#appointment_status",
)
PLACEHOLDER_PATTERN = re.compile(r"#[A-Za-z_][A-Za-z0-9_]*")

TITLES = frozenset({
    "mr", "mrs", "ms", "miss", "mister", "master", "mstr",
    "dr", "doctor", "prof", "professor", "eng", "engineer",
    "sir", "madam", "madame", "mme",
})

# A leading particle belongs to the given name that follows it, so
# "Al Mansoori Ahmed" greets as "Al Mansoori" rather than a bare "Al".
NAME_PARTICLES = frozenset({
    "al", "el", "abu", "abo", "abd", "abdul", "abdel", "abed",
    "bin", "ben", "ibn", "bint", "umm", "um",
    "van", "von", "de", "del", "della", "di", "da", "dos", "das",
    "la", "le", "mac", "mc", "st",
})


def _is_title(token):
    return token.rstrip(".").casefold() in TITLES


def _opens_like_a_name(token):
    """True when the first letter is uppercase, or from a caseless script.

    Arabic has no uppercase form, so requiring a capital would reject Arabic
    names outright; in a caseless script a letter equals both its own upper
    and lower case, which is what the second test detects.
    """
    for character in token:
        if not character.isalpha():
            continue
        return character.isupper() or character.upper() == character.lower()
    return False


def _tidy_case(token):
    # Only touch tokens that are entirely one case, so "McDonald" survives.
    if token.isupper() or token.islower():
        return token.title()
    return token


def first_name(full_name):
    """Return the greeting name from a full name as it appeared in the CSV.

    Leading honorifics are dropped and the result is tidied to title case, so
    an export row of "MR. AHMED AL MANSOORI" greets as "Ahmed". The full name
    is untouched wherever it is stored; only the rendered message is shortened.
    """
    cleaned = " ".join(str(full_name or "").split())
    if not cleaned:
        return ""
    tokens = cleaned.split(" ")
    index = 0
    while (
        index < len(tokens) - 1
        and _is_title(tokens[index])
        and _opens_like_a_name(tokens[index + 1])
    ):
        index += 1
    chosen = [tokens[index]]
    if chosen[0].rstrip(".").casefold() in NAME_PARTICLES and index + 1 < len(tokens):
        chosen.append(tokens[index + 1])
    return " ".join(_tidy_case(part) for part in chosen)


def validate_template_content(content):
    unknown = sorted(set(PLACEHOLDER_PATTERN.findall(content)) - set(PLACEHOLDER_NAMES))
    if unknown:
        raise ValidationError(
            f"Unknown message placeholder(s): {', '.join(unknown)}"
        )
    if not content.strip():
        raise ValidationError("Message template content cannot be empty.")
    return content


def format_message(template, item):
    validate_template_content(template)
    placeholders = {
        "#appointment_date": item.appointment_date.strftime("%d-%m-%Y") if item.appointment_date else "N/A",
        "#appointment_time": item.appointment_time.strftime("%I:%M %p") if item.appointment_time else "N/A",
        "#doctor": item.doctor_name_snapshot or "N/A",
        "#department": item.department_name_snapshot or "N/A",
        "#patient_name": first_name(item.patient_name_snapshot) or "N/A",
        "#mrn": item.mrn_snapshot or "N/A",
        "#appointment_status": item.get_appointment_status_display() if item.appointment_status else "N/A",
    }
    message = template
    for placeholder, value in placeholders.items():
        message = message.replace(placeholder, str(value))
    return message
