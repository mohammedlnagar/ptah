"""Composing the summary a doctor receives on WhatsApp.

Short lists name every patient; long ones give the shape of the day instead.
The cutoff exists because the summary is delivered by opening a WhatsApp URL
with the whole message encoded into it, and a busy clinic's full roster makes
that URL long enough to be truncated or rejected. The complete list is always
on screen in Ptah regardless.
"""

from messaging.formatting import display_name

DETAIL_LIMIT = 10


def _time_of(item):
    return item.appointment_time.strftime("%H:%M") if item.appointment_time else ""


def _dates(items):
    return sorted({item.appointment_date for item in items if item.appointment_date})


def _when(items):
    """A human phrase for the day or span the appointments fall on."""
    dates = _dates(items)
    if not dates:
        return ""
    if len(dates) == 1:
        return f"on {dates[0]:%d %b %Y}"
    return f"from {dates[0]:%d %b} to {dates[-1]:%d %b %Y}"


def _window(items):
    """First and last appointment time, for lists too long to enumerate."""
    times = sorted(
        item.appointment_time for item in items if item.appointment_time
    )
    if not times:
        return ""
    if times[0] == times[-1]:
        return f"{times[0]:%H:%M}"
    return f"{times[0]:%H:%M} to {times[-1]:%H:%M}"


def _totals_line(metrics):
    return (
        f"{metrics['total']} total: {metrics['booked']} booked, "
        f"{metrics['confirmed']} confirmed, {metrics['cancelled']} cancelled."
    )


def _patient_line(item, show_date):
    when = _time_of(item)
    if show_date and item.appointment_date:
        when = f"{item.appointment_date:%d %b} {when}".strip()
    name = display_name(item.patient_name_snapshot) or "Patient details removed"
    status = item.get_appointment_status_display() if item.appointment_status else ""
    parts = [part for part in (when, name) if part]
    line = "  ".join(parts)
    return f"{line} - {status}" if status else line


def build_doctor_summary(
    *, campaign_title, doctor_name, department, items, metrics, name_patients=True
):
    """Return the WhatsApp text for one doctor's appointments.

    ``name_patients`` is turned off once a list has been scrubbed, so an old
    summary never keeps identifying anyone after their details were removed.
    """
    heading = f"{doctor_name} - {campaign_title}"
    context = department or ""
    when = _when(items)
    count = f"{metrics['total']} appointment{'s' if metrics['total'] != 1 else ''}"
    detail = " · ".join(part for part in (context, f"{count} {when}".strip()) if part)

    lines = [heading]
    if detail:
        lines.append(detail)

    listed = name_patients and 0 < len(items) <= DETAIL_LIMIT
    if listed:
        show_date = len(_dates(items)) > 1
        lines.append("")
        lines.extend(_patient_line(item, show_date) for item in items)
    else:
        window = _window(items)
        if window:
            lines.append(f"Scheduled {window}.")

    lines.append("")
    lines.append(_totals_line(metrics))
    if not listed and items:
        lines.append("The full list is in Ptah.")
    return "\n".join(lines)
