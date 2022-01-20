from antelope_core.catalog_query import CatalogQuery

from .interfaces.iforeground import AntelopeForegroundInterface


class ForegroundNotSafe(Exception):
    """
    This foreground has not been loaded yet. keep our references unresolved
    """
    pass


class ForegroundQuery(CatalogQuery, AntelopeForegroundInterface):
    """
    Add foreground interface to query object
    """
    pass



class QueryIsDelayed(Exception):
    pass


class DelayedQuery(ForegroundQuery):
    """
    unresolved query that can sub itself in
    all it needs to do is raise a validation error until it's switched on
    """
    _home = None

    def __init__(self, origin, catalog, home, **kwargs):
        self._home = home
        super(DelayedQuery, self).__init__(origin, catalog, **kwargs)

    def _perform_query(self, itype, attrname, exc, *args, strict=False, **kwargs):
        if self._catalog.is_in_queue(self._home):
            raise QueryIsDelayed
        return super(DelayedQuery, self)._perform_query(itype, attrname, exc, *args, strict=strict, **kwargs)

