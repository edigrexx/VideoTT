class PipelineError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class NeedsReview(PipelineError):
    pass


class LostOwnership(Exception):
    """A restarted runner has already reclaimed this job; stale work must stop."""
