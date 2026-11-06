from pydantic import Field

from app.validation import InputModel, OutputModel


class GroupCreate(InputModel):
    name: str = Field(min_length=1, max_length=255)


class GroupUpdate(InputModel):
    name: str | None = Field(None, min_length=1, max_length=255)


class Group(OutputModel, GroupCreate):
    model_config = OutputModel.model_config
    id: int


from datetime import date  # noqa: E402

from pydantic import field_validator, model_validator  # noqa: E402

from app.enums import ContactRoleLiteral, RefKindLiteral  # noqa: E402

EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class VendorCreate(InputModel):
    name: str = Field(min_length=1, max_length=255)


class VendorUpdate(InputModel):
    name: str | None = Field(None, min_length=1, max_length=255)


class Vendor(OutputModel, VendorCreate):
    model_config = OutputModel.model_config
    id: int


class ContactFields(InputModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    email: str | None = Field(None, max_length=255, pattern=EMAIL)
    phone: str | None = Field(None, max_length=64)
    organization: str | None = Field(None, max_length=255)
    vendor_id: int | None = None

    @field_validator("email")
    @classmethod
    def _lower(cls, v):
        return v.lower() if v else v


class ContactCreate(ContactFields):
    @model_validator(mode="after")
    def _name_or_email(self):
        if not self.name and not self.email:
            raise ValueError("A contact needs a name or an email")
        return self


class ContactUpdate(ContactFields):
    pass


class Contact(OutputModel, ContactFields):
    model_config = OutputModel.model_config
    id: int


class ProjectCreate(InputModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(None, max_length=10_000)
    site_id: int | None = Field(None, description="Alias building_id")
    intake_id: str | None = Field(None, min_length=1, max_length=64, description="Unique when set")
    intake_date: date | None = None


class ProjectUpdate(InputModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=10_000)
    site_id: int | None = None
    intake_id: str | None = Field(None, min_length=1, max_length=64)
    intake_date: date | None = None


class Project(OutputModel, ProjectCreate):
    model_config = OutputModel.model_config
    id: int


class ReferenceCreate(InputModel):
    kind: RefKindLiteral
    ref: str = Field(min_length=1, max_length=64)


class Reference(OutputModel, ReferenceCreate):
    model_config = OutputModel.model_config
    id: int
    project_id: int


class ProjectContactCreate(InputModel):
    contact_id: int
    contact_role: ContactRoleLiteral
    title: str | None = Field(None, max_length=128)


class ProjectContact(OutputModel, ProjectContactCreate):
    model_config = OutputModel.model_config
    project_id: int
