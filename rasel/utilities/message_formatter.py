def format_message(template, item):
    placeholders = {
        "#appointment_date": item.appointment_date.strftime("%d-%m-%Y") if item.appointment_date else "N/A",
        "#appointment_time": item.appointment_time.strftime("%I:%M %p") if item.appointment_time else "N/A",
        "#doctor": item.doctor_name_snapshot or "N/A",
        "#department": item.department_name_snapshot or "N/A",
        "#patient_name": item.patient_name_snapshot or "N/A",
        "#mrn": item.mrn_snapshot or "N/A",
        "#appointment_status": item.get_appointment_status_display() if item.appointment_status else "N/A",
    }
    message = template
    for placeholder, value in placeholders.items():
        message = message.replace(placeholder, str(value))
    return message
