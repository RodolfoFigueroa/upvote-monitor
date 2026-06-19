from enum import Enum, IntEnum


class ApprovalStatus(IntEnum):
    REJECTED = 0
    APPROVED = 1
    UNDER_REVIEW = 2


class DownloadStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class DownloadStrategy(str, Enum):
    HTTP = "http"
    YT_DLP = "yt_dlp"


class ApprovalMode(str, Enum):
    AUTO = "auto"
    MANUAL = "manual"


class ListType(str, Enum):
    WHITELIST = "whitelist"
    BLACKLIST = "blacklist"


class RuleTargetType(str, Enum):
    COMMUNITY = "community"
    AUTHOR = "author"


class RefreshRunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
