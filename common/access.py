from django.core.exceptions import PermissionDenied


def tenant_or_403(request):
    """Return the requesting user's organization or refuse the request.

    Platform superusers have no organization, so they are refused here too:
    tenant workspaces render one organization's data and there is nothing to
    show them. They administer through the Django admin instead.
    """
    if not request.user.organization_id:
        raise PermissionDenied("Your account is not assigned to an organization.")
    if not request.user.organization.is_active:
        raise PermissionDenied("Your organization is inactive.")
    return request.user.organization
