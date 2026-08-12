from django.urls import path

from .views import (
    approve_member,
    change_member_role,
    edit_profile,
    manage_invites,
    manage_team,
    profile,
    register,
    register_with_invite,
    revoke_invite,
    suspend_member,
    user_login,
    user_logout,
    validate_registration,
)


urlpatterns = [
    path('register/', register, name='register'),
    path('register/<str:token>/', register_with_invite, name='register_with_invite'),
    path('login/', user_login, name='login'),
    path('logout/', user_logout, name='logout'),
    path('profile/', profile, name='profile'),
    path('edit-profile/', edit_profile, name='edit_profile'),
    path('validate-registration/', validate_registration, name='validate_registration'),
    path('invites/', manage_invites, name='manage_invites'),
    path('invites/<int:invite_id>/revoke/', revoke_invite, name='revoke_invite'),
    path('team/', manage_team, name='manage_team'),
    path('team/<int:user_id>/approve/', approve_member, name='approve_member'),
    path('team/<int:user_id>/suspend/', suspend_member, name='suspend_member'),
    path('team/<int:user_id>/role/', change_member_role, name='change_member_role'),
]
