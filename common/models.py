from django.core.exceptions import ValidationError
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TenantQuerySet(models.QuerySet):
    def for_organization(self, organization):
        return self.filter(organization=organization)

    def for_user(self, user):
        if user.is_superuser and user.organization_id is None:
            return self
        if user.organization_id is None:
            return self.none()
        return self.for_organization(user.organization)


class TenantModel(TimeStampedModel):
    organization = models.ForeignKey("account.Organization", on_delete=models.CASCADE)

    objects = TenantQuerySet.as_manager()

    class Meta:
        abstract = True


def validate_related_organizations(instance, *field_names):
    errors = {}
    for field_name in field_names:
        if not getattr(instance, f"{field_name}_id", None):
            continue
        related = getattr(instance, field_name)
        if related.organization_id != instance.organization_id:
            errors[field_name] = "Related records must share an organization."
    if errors:
        raise ValidationError(errors)
