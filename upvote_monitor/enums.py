from enum import IntEnum, StrEnum


class ApprovalStatus(IntEnum):
    REJECTED = 0
    APPROVED = 1
    UNDER_REVIEW = 2


class IllustrationLabel(StrEnum):
    UNLABELED = "unlabeled"
    YES = "yes"
    NO = "no"
    UNSURE = "unsure"


class DownloadStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class DownloadStrategy(StrEnum):
    HTTP = "http"
    YT_DLP = "yt_dlp"


class AnalysisStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ApprovalMode(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"


class ListType(StrEnum):
    WHITELIST = "whitelist"
    BLACKLIST = "blacklist"


class RuleTargetType(StrEnum):
    COMMUNITY = "community"
    AUTHOR = "author"


class RefreshRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
