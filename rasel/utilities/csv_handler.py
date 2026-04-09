import pandas as pd
from ..models import Contact, Appointment, AppointmentsList, AssignedMessage

from .message_formatter import format_message

# Define expected columns in CSV
CSV_COLUMNS = [
    'Appointment Date', 'Appointment Date/Time', 'MR No.', 'Patient Name',
    'Patient Mobile', 'Consultant', 'Doctor Department', 'Visit Id',
    'Consultation Type', 'Appointment Status', 'Appointment Source',
    'Complaint', 'Duration (Min)', 'Other Resources', 'Cancel Reason',
    'Cancelled Date/Time', 'Patient Category', 'Remarks'
]

# Date columns that need parsing
DATE_COLUMNS = ['Appointment Date', 'Appointment Date/Time', 'Cancelled Date/Time']

def clean_csv_data(file):
    """Reads and cleans the CSV file data, ensuring proper formatting."""
    try:
        # df = pd.read_csv(file, skiprows=2, parse_dates=DATE_COLUMNS)
        df = pd.read_csv(file, header=None, engine="pyarrow", dtype_backend="pyarrow")
        valid_rows = df.dropna(thresh=3)
        valid_header = valid_rows.index[0]
        valid_footer = valid_rows.index[-1]
        df = df.loc[valid_header:valid_footer].reset_index(drop=True)
        df.columns = df.iloc[0].reset_index(drop=True)  # Set the first valid row as header
        df.columns.name = None  # Remove the name of the columns index
        df = df[1:].reset_index(drop=True)  # Remove the header row from data
        df['Appointment Date'] = pd.to_datetime(df['Appointment Date'], format='%d-%m-%Y')
        df['Appointment Date/Time'] = pd.to_datetime(df['Appointment Date/Time'], format= '%d-%m-%Y %H:%M')
        # Ensure the required columns are present
        missing_cols = [col for col in CSV_COLUMNS if col not in df.columns]
        if missing_cols:
            raise ValueError(f"Missing columns in CSV: {', '.join(missing_cols)}")

        # Drop rows without an appointment date
        # df.dropna(subset=['Appointment Date'], inplace=True)

       

        # Convert Patient Mobile to string (avoid scientific notation issues)
        df['Patient Mobile'] = df['Patient Mobile'].astype(str).str.replace('.0', '', regex=False)

        # Handle missing 'MR No.' values
        df['MR No.'].fillna('New Client', inplace=True)

        return df

    except Exception as e:
        raise ValueError(f"Error processing CSV file: {str(e)}")



def save_appointments_from_csv(user, file, list_title, messages):
    """
    Processes CSV, creates a new AppointmentsList, and stores Contact, Appointment, and AssignedMessage records.
    """
    try:
        df = clean_csv_data(file)
        only_scheduled = df['Appointment Status'] != "Cancelled"
        df = df[only_scheduled]
        # Create new AppointmentsList
        appointments_list = AppointmentsList.objects.create(
            title=list_title,
            author=user
        )

        # Assign selected messages to the list
        appointments_list.message_selected.set(messages)

        contacts_cache = {c.phone_number: c for c in Contact.objects.all()}  # Cache existing contacts
        appointments_to_create = []
        assigned_messages_to_create = []

        for _, row in df.iterrows():
            phone_number = row['Patient Mobile']
            contact = contacts_cache.get(phone_number)

            if not contact:
                contact = Contact.objects.create(
                    phone_number=phone_number,
                    name=row['Patient Name']
                )
                contacts_cache[phone_number] = contact

            # Create appointment instance
            appointment = Appointment.objects.create(
                contact=contact,
                appointments_list=appointments_list,
                doctor_name=row['Consultant'],
                appointment_date=row['Appointment Date'].date() if pd.notna(row['Appointment Date/Time']) else None,
                appointment_time=row['Appointment Date/Time'].time() if pd.notna(row['Appointment Date/Time']) else None,
                appointment_remarks=row['Remarks'],
                appointment_status=row['Appointment Status']
            )

            # Generate and assign personalized message using the first template
            if messages.exists():
                template = messages.first()
                custom_message = format_message(template.content, appointment)

                assigned_messages_to_create.append(AssignedMessage(
                    appointment=appointment,
                    message_template=template,
                    custom_message=custom_message,
                    status='pending'
                ))

        # Bulk create assigned messages
        AssignedMessage.objects.bulk_create(assigned_messages_to_create)

        return appointments_list

    except Exception as e:
        print(f"CSV Processing Error: {e}")
        return None
