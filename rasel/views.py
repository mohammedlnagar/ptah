from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import AppointmentsList, MessageTemplate, Appointment, AssignedMessage, Contact
from .forms import AppointmentsListForm, MessageTemplateForm
from .utilities.csv_handler import save_appointments_from_csv
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from .utilities.message_formatter import format_message
from urllib.parse import quote  # Use Python's built-in quote function for URL encoding
from django.db.models import Q
from django.core.paginator import Paginator
from django.contrib import messages


from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt

@login_required
def manage_appointments_and_messages(request):
    """
    Handles appointment list creation and message template creation on the same page.
    Uses AJAX for asynchronous processing.
    """
    if request.method == "POST":
        form_type = request.POST.get("form_type")

        # Handle appointment list creation
        if form_type == "appointments_list":
            form = AppointmentsListForm(request.POST, request.FILES)
            if form.is_valid():
                csv_file = request.FILES['csv_file']
                list_title = form.cleaned_data['title']
                appointment_messages = form.cleaned_data['message_selected']

                new_list = save_appointments_from_csv(request.user, csv_file, list_title, appointment_messages)

                if new_list:
                    messages.success(request, "Appointment list created successfully!")
                    return JsonResponse({"success": True, "message": "Appointment list created successfully!"})
                
                return JsonResponse({"success": False, "message": "Error processing CSV file."})
            return JsonResponse({"success": False, "message": "Invalid form data."})

        # Handle message template creation
        elif form_type == "message_template":
            messageform = MessageTemplateForm(request.POST)
            if messageform.is_valid():
                messageform.save()
                messages.success(request, "Message template created successfully!")

                return JsonResponse({"success": True, "message": "Message template created successfully!"})
            return JsonResponse({"success": False, "message": "Invalid form data."})

    # Fetch existing lists and messages
    appointment_lists = AppointmentsList.objects.all()
    appointment_messages = MessageTemplate.objects.all()

    return render(request, "rasel/contact_lists.html", {
        "appointments_list_form": AppointmentsListForm(),
        "message_template_form": MessageTemplateForm(),
        "appointment_lists": appointment_lists,
        "messages": appointment_messages
    })

 

@login_required
def appointment_list_detail(request, list_id):
    """
    Displays details of a specific appointment list with customized messages.
    """
    appointment_list = get_object_or_404(AppointmentsList, id=list_id)
    assigned_messages = AssignedMessage.objects.filter(appointment__appointments_list=appointment_list)

    
    # Fetch unique doctor names for the dropdown
    doctors = Appointment.objects.filter(appointments_list=appointment_list).values_list('doctor_name', flat=True).distinct()

    return render(request, "rasel/list_detail.html", {
        "appointment_list": appointment_list,
        "assigned_messages": assigned_messages,
        "doctors": doctors,
    })



@csrf_exempt
@require_POST
def edit_assigned_message(request):
    """
    AJAX endpoint to update the custom message of an assigned message.
    """
    try:
        message_id = int(request.POST.get("message_id"))
        new_message = request.POST.get("new_message")

        assigned_message = AssignedMessage.objects.get(id=message_id)
        assigned_message.custom_message = new_message
        assigned_message.save()
        
        print(f'Message Changed___________________________: {new_message}')

        return JsonResponse({"success": True, "message": "Message updated successfully!"})
    except AssignedMessage.DoesNotExist:
        return JsonResponse({"success": False, "message": "Assigned message not found."})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)})

@csrf_exempt
@require_POST
def update_assigned_message_status(request):
    """
    AJAX endpoint to update the status of an assigned message.
    """
    try:
        message_id = int(request.POST.get("message_id"))
        new_status = request.POST.get("status")

        assigned_message = AssignedMessage.objects.get(id=message_id)
        assigned_message.status = new_status
        assigned_message.save()

        return JsonResponse({"success": True, "message": "Status updated successfully!"})
    except AssignedMessage.DoesNotExist:
        return JsonResponse({"success": False, "message": "Assigned message not found."})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)})

from django.core.paginator import Paginator

@csrf_exempt
def filter_assigned_messages(request, list_id):
    """
    Filters assigned messages based on doctor name and message status.
    Automatically paginates lists with more than 15 messages.
    """
    try:
        doctor = request.GET.get("doctor", "").strip()
        status = request.GET.get("status", "").strip()
        page = int(request.GET.get("page", 1))  # Get the current page number

        appointment_list = get_object_or_404(AppointmentsList, id=list_id)

        filters = Q(appointment__appointments_list=appointment_list)

        if doctor:
            filters &= Q(appointment__doctor_name__icontains=doctor)
        if status:
            filters &= Q(status=status)

        assigned_messages = AssignedMessage.objects.filter(filters)

        # Check if pagination is necessary
        paginate = assigned_messages.count() > 15
        paginator = Paginator(assigned_messages, 15) if paginate else None
        page_obj = paginator.get_page(page) if paginate else assigned_messages

        # Prepare data for JSON response
        filtered_data = []
        for message in page_obj:
            filtered_data.append({
                "id": message.id,
                "patient_name": message.appointment.contact.name,
                "doctor_name": message.appointment.doctor_name,
                "appointment_date": message.appointment.appointment_date.strftime("%d-%m-%Y") if message.appointment.appointment_date else "N/A",
                "appointment_time": message.appointment.appointment_time.strftime("%I:%M %p") if message.appointment.appointment_time else "N/A",
                "custom_message": message.custom_message,
                "status": message.status
            })

        return JsonResponse({
            "success": True,
            "data": filtered_data,
            "paginate": paginate,
            "num_pages": paginator.num_pages if paginate else 1,
            "current_page": page_obj.number if paginate else 1
        })
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)})


import csv
from django.http import HttpResponse

@login_required
def export_assigned_messages_to_csv(request, list_id):
    """
    Exports filtered assigned messages as a CSV file.
    """
    try:
        doctor = request.GET.get("doctor", "").strip()
        status = request.GET.get("status", "").strip()

        appointment_list = get_object_or_404(AppointmentsList, id=list_id)

        filters = Q(appointment__appointments_list=appointment_list)

        if doctor:
            filters &= Q(appointment__doctor_name__icontains=doctor)
        if status:
            filters &= Q(status=status)

        assigned_messages = AssignedMessage.objects.filter(filters)

        # Create the HttpResponse object with CSV header
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="assigned_messages_list_{list_id}.csv"'

        writer = csv.writer(response)
        # Write the CSV header
        writer.writerow(["Patient Name", "Doctor Name", "Appointment Date", "Appointment Time", "Message", "Status"])

        # Write message data to CSV
        for message in assigned_messages:
            writer.writerow([
                message.appointment.contact.name,
                message.appointment.doctor_name,
                message.appointment.appointment_date.strftime("%d-%m-%Y") if message.appointment.appointment_date else "N/A",
                message.appointment.appointment_time.strftime("%I:%M %p") if message.appointment.appointment_time else "N/A",
                message.custom_message,
                message.status.capitalize()
            ])

        return response
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)})

@csrf_exempt
@require_POST
def update_contact_details(request):
    """
    AJAX endpoint to update contact details (name and phone number).
    """
    try:
        contact_id = int(request.POST.get("contact_id"))
        new_name = request.POST.get("name").strip()
        new_phone_number = request.POST.get("phone_number").strip()

        contact = Contact.objects.get(id=contact_id)
        contact.name = new_name
        contact.phone_number = new_phone_number
        contact.save()

        return JsonResponse({"success": True, "message": "Contact updated successfully!"})
    except Contact.DoesNotExist:
        return JsonResponse({"success": False, "message": "Contact not found."})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)})
