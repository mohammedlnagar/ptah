from django.urls import path

from . import views


urlpatterns = [
    path("AppointmentsManage/", views.manage_appointments_and_messages, name="manage_appointments"),
    path("list/<int:list_id>/", views.appointment_list_detail, name="appointment_list_detail"),
    path("EditMessage/", views.edit_assigned_message, name="EditMessage"),
    path("update-message-status/", views.update_assigned_message_status, name="update_assigned_message_status"),
    path("message/<int:message_id>/whatsapp/", views.open_whatsapp_message, name="open_whatsapp_message"),
    path("doctor-summary/<int:summary_id>/whatsapp/", views.open_doctor_summary, name="open_doctor_summary"),
    path("item/<int:item_id>/appointment-status/", views.update_appointment_status, name="update_appointment_status"),
    path("list/<int:list_id>/filter-messages/", views.filter_assigned_messages, name="filter_assigned_messages"),
    path("list/<int:list_id>/export-csv/", views.export_assigned_messages_to_csv, name="export_assigned_messages_to_csv"),
    path("update-contact/", views.update_contact_details, name="update_contact_details"),
]
