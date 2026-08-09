import pytest

from apps.content.models import MasterContent, PlatformContent
from apps.content.services import ContentStateError, master_transition, platform_transition


@pytest.mark.parametrize(
    ("source", "action", "expected"),
    [
        (MasterContent.Status.DRAFT, "SUBMIT", MasterContent.Status.IN_REVIEW),
        (MasterContent.Status.IN_REVIEW, "APPROVE", MasterContent.Status.APPROVED),
        (MasterContent.Status.IN_REVIEW, "REJECT", MasterContent.Status.REJECTED),
        (MasterContent.Status.APPROVED, "ARCHIVE", MasterContent.Status.ARCHIVED),
    ],
)
def test_master_transition_accepts_only_canonical_edges(source, action, expected):
    assert master_transition(source, action, comment="reason") == expected


@pytest.mark.parametrize(
    ("source", "action"),
    [
        (MasterContent.Status.DRAFT, "APPROVE"),
        (MasterContent.Status.APPROVED, "REJECT"),
        (MasterContent.Status.ARCHIVED, "SUBMIT"),
        (MasterContent.Status.IN_REVIEW, "PUBLISH"),
    ],
)
def test_master_transition_rejects_invalid_edges(source, action):
    with pytest.raises(ContentStateError):
        master_transition(source, action, comment="reason")


def test_reject_requires_comment_for_both_content_types():
    with pytest.raises(ContentStateError):
        master_transition(MasterContent.Status.IN_REVIEW, "REJECT", comment=" ")
    with pytest.raises(ContentStateError):
        platform_transition(PlatformContent.Status.IN_REVIEW, "REJECT", comment="")


def test_platform_supports_published_but_master_does_not():
    assert platform_transition(
        PlatformContent.Status.APPROVED, "PUBLISH", comment=""
    ) == PlatformContent.Status.PUBLISHED
    with pytest.raises(ContentStateError):
        master_transition(MasterContent.Status.APPROVED, "PUBLISH", comment="")
