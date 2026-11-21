"""Validated application profiles built on ``comuvia/0.1`` records.

- ``comuvia.profiles.dependencies``: ``org.comuvia.dependencies/v1`` and ``v2``
  (declared input pins, origin/meaning/coverage checks, and correction impact with
  optional structured ``v2`` selection-slice resolution).
- ``comuvia.profiles.edition_review``: ``edition-review/1``, ``review-summary/1`` and
  ``contribution/1`` (binding a review decision to the exact bytes and revisions of an
  edition's members and summary).
"""

from . import dependencies, edition_review

__all__ = ["dependencies", "edition_review"]
