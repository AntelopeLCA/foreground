class ForegroundNotSafe(Exception):
    """
    This foreground has not been loaded yet. keep our references unresolved
    """
    pass


class BackReference(Exception):
    """
    trying to instantiate a foreground that's currently being loaded
    """
    pass


